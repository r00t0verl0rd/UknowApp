import { Dynamic } from "@solidjs/web";
export default function CountBadge(options) {
  const count = () => Math.max(0, Number(options.value) || 0);
  return () => {
    if ((options.hideWhenZero ?? false) && count() === 0) return null;
    const Element = () => ((options.as ?? "span") === "b" ? "b" : "span");
    const formatted = () => (count() > (options.max ?? 99) ? `${options.max ?? 99}+` : count());
    const accessibleLabel = () => (options.label ? `${formatted()} ${options.label}` : undefined);
    return (
      <Dynamic
        component={Element()}
        class={[
          "chat-tab-count",
          (options.unread ?? false) && "chat-tab-count--unread",
          options.className ?? "",
        ]
          .filter(Boolean)
          .join(" ")}
        title={options.title}
        aria-label={accessibleLabel()}
      >
        {formatted()}
      </Dynamic>
    );
  };
}
