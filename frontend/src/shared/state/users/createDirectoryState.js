import { createSignal } from "solid-js";
export function createDirectoryState() {
  const [users, setUsers] = createSignal([]);
  const [overview, setOverview] = createSignal(null);
  const [search, setSearch] = createSignal("");
  const [userSort, setUserSort] = createSignal("students");
  const [userInfo, setUserInfo] = createSignal(null);
  return {
    get users() {
      return users();
    },
    setUsers,
    get overview() {
      return overview();
    },
    setOverview,
    get search() {
      return search();
    },
    setSearch,
    get userSort() {
      return userSort();
    },
    setUserSort,
    get userInfo() {
      return userInfo();
    },
    setUserInfo,
  };
}
