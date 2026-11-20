import { useState } from "react";

export function useDirectoryState() {
  const [users, setUsers] = useState([]);
  const [overview, setOverview] = useState(null);
  const [search, setSearch] = useState("");
  const [userSort, setUserSort] = useState("students");
  const [userInfo, setUserInfo] = useState(null);
  return { users, setUsers, overview, setOverview, search, setSearch, userSort, setUserSort, userInfo, setUserInfo };
}
