"""Prototype operating assumptions, owned by this feature.

The public input remains core.scenario.Scenario. Additional UI inputs require
the integration owner's change to that shared contract; none are added here.
"""
SETTINGS = {
    'store_count': 3,
    'max_hubs': 2,
    'scenarios': 8,
    'travel_minutes': 30,
    'preparation_minutes': 10,
    'receiving_minutes': 5,
    'capacity_liters': {'chilled': 200, 'frozen': 200, 'ambient': 150},
    'vehicle_count': 1,
    'vehicle_minutes_per_day': 360,
    'trip_cost': 0,
    'hub_daily_cost': 12000,
    'split_allowed': False,
    'matrix': {},
    'hub_stock': {},
}
