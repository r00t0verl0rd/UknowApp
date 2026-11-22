import { Dynamic } from "@solidjs/web";
import { omit } from "solid-js";
const ELEMENTS = Object.freeze({
  section: "section",
  article: "article",
  div: "div",
});
export default function Panel(options) {
  const props = omit(options, "as", "className", "children");
  const Element = () => ELEMENTS[options.as ?? "section"] || ELEMENTS.section;
  return (
    <Dynamic
      component={Element()}
      {...props}
      class={["graph-panel", options.className ?? ""].filter(Boolean).join(" ")}
    >
      {options.children}
    </Dynamic>
  );
}
