import { useState } from "react";

export function useGraphState() {
  const [teacherGraph, setTeacherGraph] = useState(null);
  const [graphObjects, setGraphObjects] = useState([]);
  return { teacherGraph, setTeacherGraph, graphObjects, setGraphObjects };
}
