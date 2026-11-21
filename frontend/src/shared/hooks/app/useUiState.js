import { useCallback, useEffect, useState } from "react";

const PAGE_PATHS = Object.freeze({
  graph: "/structure",
  chats: "/dialogs",
  users: "/users",
  boards: "/boards",
  additional: "/additional",
});

const PATH_PAGES = Object.freeze(
  Object.fromEntries(Object.entries(PAGE_PATHS).map(([page, path]) => [path, page])),
);

function readPageFromLocation() {
  const pathname = window.location.pathname.replace(/\/+$/, "") || "/";
  return PATH_PAGES[pathname] || "graph";
}

export function useUiState() {
  const [page, setPageState] = useState(readPageFromLocation);
  const setPage = useCallback((nextPage, options = {}) => {
    const pathname = PAGE_PATHS[nextPage];
    if (!pathname) return;

    const nextUrl = pathname + window.location.search + window.location.hash;
    const currentUrl = window.location.pathname + window.location.search + window.location.hash;
    if (currentUrl !== nextUrl) {
      const method = options.replace ? "replaceState" : "pushState";
      window.history[method]({ page: nextPage }, "", nextUrl);
    }

    setPageState(current => current === nextPage ? current : nextPage);
  }, []);

  useEffect(() => {
    const handlePopState = () => setPageState(readPageFromLocation());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const [modal, setModal] = useState(null);
  return { page, setPage, modal, setModal };
}
