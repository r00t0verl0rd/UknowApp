import { useState } from "react";

export function useGraphState() {
  const [teacherGraph, setTeacherGraph] = useState(null);
  return { teacherGraph, setTeacherGraph };
}
