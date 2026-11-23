import { dynamic } from "@solidjs/web";
import { Show } from "solid-js";

export default function CountBadge(props) {
  const count = () => Math.max(0, Number(props.value) || 0);
  const formatted = () => count();
  const Badge = dynamic(() => (props.as === "b" ? "b" : "span"));

  return (
    <Show when={!props.hideWhenZero || count() > 0}>
      <Badge
        class={props.unread ? "chat-tab-count chat-tab-count--unread" : "chat-tab-count"}
        title={props.title}
        aria-label={props.label ? `${formatted()} ${props.label}` : undefined}
      >
        {formatted()}
      </Badge>
    </Show>
  );
}
