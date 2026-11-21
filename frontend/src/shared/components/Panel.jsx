const ELEMENTS = Object.freeze({
  section: "section",
  article: "article",
  div: "div",
});

export default function Panel({
  as = "section",
  className = "",
  children,
  ...props
}) {
  const Element = ELEMENTS[as] || ELEMENTS.section;
  return (
    <Element {...props} className={["graph-panel", className].filter(Boolean).join(" ")}>
      {children}
    </Element>
  );
}
