import type { ReactNode } from "react";
export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border border-[#e6e7df] bg-white p-5 md:p-6 ${className}`}
    >
      {title && (
        <h2 className="mb-5 text-[16px] font-semibold text-[#333028]">{title}</h2>
      )}
      {children}
    </section>
  );
}
export function PageHeader({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="mb-6">
      <h1 className="text-[28px] leading-tight font-bold tracking-[-.03em] text-[#29271f] md:text-[32px]">
        {title}
      </h1>
      {description && (
        <p className="mt-2 text-[15px] leading-7 text-[#716d63]">{description}</p>
      )}
    </header>
  );
}
export function JsonView({ value }: { value: unknown }) {
  return (
    <pre className="overflow-x-auto rounded-xl bg-[#20251c] p-4 text-xs leading-relaxed text-[#dfe6d4]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
