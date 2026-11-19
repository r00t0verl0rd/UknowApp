import { useRef, useState } from "react";

export function useGraphState() {
  const [teacherGraph, setTeacherGraph] = useState(null);
  const [collapsedTeacherIds, setCollapsedTeacherIds] = useState(() => new Set());
  return { teacherGraph, setTeacherGraph, collapsedTeacherIds, setCollapsedTeacherIds };
}
