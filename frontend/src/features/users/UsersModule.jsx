import { viewAccountKey } from "../../shared/services/viewSession.js";
import UsersPage from "./UsersPage.jsx";
import UserDialogs from "./components/UserDialogs.jsx";
import StructurePage from "../graph/StructurePage.jsx";
import { createUsersController } from "../../shared/state/users/createUsersController.js";
export default function UsersModule(options) {
  const state = createUsersController({
    request: options.request,
    refresh: options.refresh,
    notify: options.notify,
    setError: options.setError,
    get selectedChat() {
      return options.selectedChat;
    },
    setSelectedChat: options.setSelectedChat,
    setMessages: options.setMessages,
    get modal() {
      return options.modal;
    },
    setModal: options.setModal,
    directory: options.directory,
  });
  return (
    <>
      {options.page === "users" && (
        <UsersPage
          visibleUsers={state.visibleUsers}
          search={state.search}
          setSearch={state.setSearch}
          userSort={state.userSort}
          setUserSort={state.setUserSort}
          openCreate={state.openCreate}
          disconnectTelegram={state.disconnectTelegram}
          openTelegram={(user, platform = "telegram") => options.setModal({ mode: "telegram", platform, id: user.id, user })}
          userInfo={state.userInfo}
          setUserInfo={state.setUserInfo}
          openEdit={state.openEdit}
          removeUser={state.removeUser}
        />
      )}
      {options.page === "graph" && (
        <StructurePage
          userId={viewAccountKey(options.profile)}
          overview={state.overview}
          loading={options.adminDataLoading}
          openCreate={state.openCreate}
          allTeachers={state.allTeachers}
          studentsByTeacherId={state.studentsByTeacherId}
          openEdit={state.openEdit}
          setTeacherId={state.setTeacherId}
          setStudentId={state.setStudentId}
          allStudents={state.allStudents}
          setModal={options.setModal}
          unassignedStudents={state.unassignedStudents}
          unassignStudent={state.requestUnassignStudent}
        />
      )}
      <UserDialogs
        modal={options.modal}
        setModal={options.setModal}
        assign={state.assign}
        teacherId={state.teacherId}
        setTeacherId={state.setTeacherId}
        allTeachers={state.allTeachers}
        studentId={state.studentId}
        setStudentId={state.setStudentId}
        allStudents={state.allStudents}
        saveUser={state.saveUser}
        name={state.name}
        setName={state.setName}
        panelLogin={state.panelLogin}
        setPanelLogin={state.setPanelLogin}
        role={state.role}
        setRole={state.setRole}
        additionalInfo={state.additionalInfo}
        setAdditionalInfo={state.setAdditionalInfo}
        maxId={state.maxId}
        setMaxId={state.setMaxId}
        telegramId={state.telegramId}
        setTelegramId={state.setTelegramId}
        users={state.users}
        savingUser={state.savingUser}
        openEdit={state.openEdit}
        makeCode={state.makeCode}
        regeneratePanelAccessCode={state.regeneratePanelAccessCode}
        removeUser={state.removeUser}
        deleteCandidate={state.deleteCandidate}
        setDeleteCandidate={state.setDeleteCandidate}
        deletingUser={state.deletingUser}
        confirmRemoveUser={state.confirmRemoveUser}
        disconnectCandidate={state.disconnectCandidate}
        setDisconnectCandidate={state.setDisconnectCandidate}
        disconnectingTelegram={state.disconnectingTelegram}
        confirmDisconnectTelegram={state.confirmDisconnectTelegram}
        issuedCredential={state.issuedCredential}
        setIssuedCredential={state.setIssuedCredential}
        notify={options.notify}
        code={state.code}
        setCode={state.setCode}
        unassignCandidate={state.unassignCandidate}
        setUnassignCandidate={state.setUnassignCandidate}
        unassigningStudent={state.unassigningStudent}
        confirmUnassignStudent={state.confirmUnassignStudent}
      />
    </>
  );
}
