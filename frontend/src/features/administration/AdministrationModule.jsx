import AdditionalPage from "./AdditionalPage.jsx";
import { createAdminDataController } from "../../shared/state/administration/createAdminDataController.js";
export default function AdministrationModule(options) {
  const state = createAdminDataController({
    get auth() {
      return options.auth;
    },
    get profile() {
      return options.profile;
    },
    get page() {
      return options.page;
    },
    request: options.request,
    refresh: options.refresh,
    notify: options.notify,
    setError: options.setError,
    setSelectedChat: options.setSelectedChat,
    setMessages: options.setMessages,
  });
  return () => {
    if (options.page !== "additional") return null;
    return (
      <AdditionalPage
        dataStats={state.dataStats}
        restore={state.restore}
        dataBusy={state.dataBusy}
        loadDataStats={state.loadDataStats}
        downloadAdminFile={state.downloadAdminFile}
        uploadAdminFile={state.uploadAdminFile}
        retentionDays={state.retentionDays}
        setRetentionDays={state.setRetentionDays}
        cleanupOldDialogues={state.cleanupOldDialogues}
        pendingConfirmation={state.pendingConfirmation}
        setPendingConfirmation={state.setPendingConfirmation}
        confirmPendingAction={state.confirmPendingAction}
      />
    );
  };
}
