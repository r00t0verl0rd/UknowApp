import { createSignal } from "solid-js";
export function createUserEditorState() {
  const [issuedCredential, setIssuedCredential] = createSignal(null);
  const [savingUser, setSavingUser] = createSignal(false);
  const [name, setName] = createSignal("");
  const [panelLogin, setPanelLogin] = createSignal("");
  const [role, setRole] = createSignal("teacher");
  const [additionalInfo, setAdditionalInfo] = createSignal("");
  const [telegramId, setTelegramId] = createSignal("");
  const [teacherId, setTeacherId] = createSignal("");
  const [studentId, setStudentId] = createSignal("");
  const [code, setCode] = createSignal(null);
  return {
    get issuedCredential() {
      return issuedCredential();
    },
    setIssuedCredential,
    get savingUser() {
      return savingUser();
    },
    setSavingUser,
    get name() {
      return name();
    },
    setName,
    get panelLogin() {
      return panelLogin();
    },
    setPanelLogin,
    get role() {
      return role();
    },
    setRole,
    get additionalInfo() {
      return additionalInfo();
    },
    setAdditionalInfo,
    get telegramId() {
      return telegramId();
    },
    setTelegramId,
    get teacherId() {
      return teacherId();
    },
    setTeacherId,
    get studentId() {
      return studentId();
    },
    setStudentId,
    get code() {
      return code();
    },
    setCode,
  };
}
