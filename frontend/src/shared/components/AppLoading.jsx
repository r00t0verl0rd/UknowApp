export default function AppLoading({ label }) {
  return <div className="login-screen" role="status" aria-live="polite">
    <div className="empty-state">{label}</div>
  </div>;
}
