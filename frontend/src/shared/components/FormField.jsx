export default function FormField(props) {
  return (
    <label>
      <span>{props.label}</span>
      {props.children}
    </label>
  );
}
