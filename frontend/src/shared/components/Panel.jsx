import { omit } from "solid-js";

export default function Panel(props) {
  const attributes = omit(props, "class", "children");
  return (
    <section {...attributes} class={["graph-panel", props.class].filter(Boolean).join(" ")}>
      {props.children}
    </section>
  );
}
