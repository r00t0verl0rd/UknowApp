export default function FormField({
  label,
  htmlFor,
  hint,
  className = "",
  children,
  ...props
}) {
  return (
    <label {...props} htmlFor={htmlFor} className={className || undefined}>
      <span>{label}</span>
      {children}
      {hint && <small className="hint">{hint}</small>}
    </label>
  );
}
