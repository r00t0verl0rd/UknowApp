import { omit } from "solid-js";

export default function Panel(props) {
  const attributes = omit(props, "className", "children");
  return (
    <section {...attributes} class={["graph-panel", props.className].filter(Boolean).join(" ")}>
      {props.children}
    </section>
  );
}
