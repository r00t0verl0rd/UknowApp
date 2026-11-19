import { useRef, useState } from "react";

export function useUserEditorState() {
  const [issuedCredential, setIssuedCredential] = useState(null);
  const [savingUser, setSavingUser] = useState(false);
  const [name, setName] = useState("");
  const [panelLogin, setPanelLogin] = useState("");
  const [role, setRole] = useState("teacher");
  const [additionalInfo, setAdditionalInfo] = useState("");
  const [telegramId, setTelegramId] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [studentId, setStudentId] = useState("");
  const [code, setCode] = useState(null);
  return {
    issuedCredential, setIssuedCredential, savingUser, setSavingUser,
    name, setName, panelLogin, setPanelLogin, role, setRole, additionalInfo, setAdditionalInfo,
    telegramId, setTelegramId, teacherId, setTeacherId, studentId, setStudentId, code, setCode,
  };
}
