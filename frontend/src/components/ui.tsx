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
        <h2 className="mb-5 text-[13px] font-bold text-[#333a2a]">{title}</h2>
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
      <h1 className="text-[26px] leading-tight font-bold tracking-[-.04em] text-[#23271f] md:text-[30px]">
        {title}
      </h1>
      {description && (
        <p className="mt-2 text-xs leading-6 text-[#8a927e]">{description}</p>
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
