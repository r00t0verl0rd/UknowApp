import { useState } from "react";

export function useGraphState() {
  const [teacherGraph, setTeacherGraph] = useState(null);
  const [graphObjects, setGraphObjects] = useState([]);
  const [collapsedTeacherIds, setCollapsedTeacherIds] = useState(() => new Set());
  return { teacherGraph, setTeacherGraph, graphObjects, setGraphObjects, collapsedTeacherIds, setCollapsedTeacherIds };
}
