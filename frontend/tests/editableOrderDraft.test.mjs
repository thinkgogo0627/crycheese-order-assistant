// Node 24+ supports the erasable TypeScript used by the helper.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyOrderQuantity, readOrderQuantity, orderDraftCsv, orderMinimumChecks } from '../src/lib/editableOrderDraft.ts'

const row=Object.freeze({store_id:'H01',ingredient_id:'I1',ingredient_name:'슬라이스 "치즈"',supplier_id:'SUP_A',order_date:'2026-10-01',arrival_date:'2026-10-02',order_qty:3,order_unit:'BOX',use_qty:360,safety_qty:100,use_unit:'매',amount:162300,status:'DRAFT',basis:'추천 근거'})
test('only nonnegative safe integers are accepted',()=>{
 for(const value of ['', '-1', '1.5', '1e2', 'NaN', 'Infinity', '9007199254740992'])assert.equal(readOrderQuantity(value),null,value)
 assert.equal(readOrderQuantity('0'),0)
 assert.equal(readOrderQuantity('12'),12)
})
test('recommendation defaults and original object stay intact',()=>{
 assert.deepEqual(applyOrderQuantity(row,'3'),row)
 assert.equal(row.order_qty,3)
})
test('edited amount and use quantity follow packaging ratio',()=>{
 const edited=applyOrderQuantity(row,'5')
 assert.equal(edited.order_qty,5)
 assert.equal(edited.use_qty,600)
 assert.equal(edited.amount,270500)
 assert.equal(row.amount,162300)
})
test('zero excludes an order and large amounts fail safely',()=>{
 const excluded=applyOrderQuantity(row,'0')
 assert.equal(excluded.amount,0)
 assert.equal(orderDraftCsv([excluded]).split('\r\n').length,1)
 assert.equal(applyOrderQuantity(row,'9007199254740991'),null)
})
test('CSV uses edited integers and amounts and escapes quotes',()=>{
 const csv=orderDraftCsv([{...applyOrderQuantity(row,'5'),status:'수량 수정'}])
 assert(csv.includes('"5","BOX","270500","수량 수정"'))
 assert(csv.includes('"슬라이스 ""치즈"""'))
 assert(!csv.includes('162300'))
})
test('supplier total controls warning, not original review status or each line',()=>{
 const a={...row,order_qty:1,amount:60000,minimum_amount:100000,status:'MIN_AMOUNT_REVIEW'}
 const b={...a,ingredient_id:'I2'}
 assert.equal(orderMinimumChecks([a,b],[a,b])[0].below,false)
 const reduced=applyOrderQuantity(a,'0')
 assert.equal(orderMinimumChecks([a,b],[reduced,b])[0].below,true)
 const restored=applyOrderQuantity(b,'2')
 assert.equal(orderMinimumChecks([a,b],[reduced,restored])[0].below,false)
})
test('exact threshold is enough, and cancelled or invalid groups do not show shortage',()=>{
 const a={...row,order_qty:1,amount:100000,minimum_amount:100000}
 assert.equal(orderMinimumChecks([a],[a])[0].below,false)
 assert.equal(orderMinimumChecks([a],[applyOrderQuantity(a,'0')])[0].below,false)
 assert.equal(orderMinimumChecks([a],[null])[0].below,false)
})
test('store, supplier and date each separate minimum checks',()=>{
 const a={...row,order_qty:1,amount:40000,minimum_amount:50000}
 const rows=[a,{...a,store_id:'S02'},{...a,supplier_id:'SUP_B'},{...a,order_date:'2026-10-02'}]
 const groups=orderMinimumChecks(rows,rows)
 assert.equal(groups.length,4)
 assert(groups.every(group=>group.below))
})
test('no minimum means no warning, including emergency orders',()=>{
 const a={...row,minimum_amount:0,status:'MIN_AMOUNT_REVIEW'}
 assert.equal(orderMinimumChecks([a],[a])[0].below,false)
})
