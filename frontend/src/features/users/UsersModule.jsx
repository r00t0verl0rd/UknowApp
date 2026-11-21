import UsersPage from "./UsersPage.jsx";
import UserDialogs from "./components/UserDialogs.jsx";
import StructurePage from "../graph/StructurePage.jsx";
import { useUsersController } from "../../shared/hooks/users/useUsersController.js";

export default function UsersModule({
  page, directory, request, refresh, notify, setError, adminDataLoading,
  selectedChat, setSelectedChat, setMessages, modal, setModal,
}) {
  const state = useUsersController({
    request, refresh, notify, setError, selectedChat, setSelectedChat,
    setMessages, modal, setModal, directory,
  });

  return <>
    {page === "users" && <UsersPage
      visibleUsers={state.visibleUsers} loading={adminDataLoading} search={state.search} setSearch={state.setSearch}
      userSort={state.userSort} setUserSort={state.setUserSort}
      openCreate={state.openCreate} disconnectTelegram={state.disconnectTelegram}
      makeCode={state.makeCode} userInfo={state.userInfo} setUserInfo={state.setUserInfo}
      openEdit={state.openEdit} removeUser={state.removeUser}
    />}
    {page === "graph" && <StructurePage
      overview={state.overview} loading={adminDataLoading}
      openCreate={state.openCreate} allTeachers={state.allTeachers}
      studentsByTeacherId={state.studentsByTeacherId} openEdit={state.openEdit}
      setTeacherId={state.setTeacherId} setStudentId={state.setStudentId}
      allStudents={state.allStudents} setModal={setModal}
      unassignedStudents={state.unassignedStudents} unassignStudent={state.requestUnassignStudent}
    />}
    <UserDialogs
      modal={modal} setModal={setModal} assign={state.assign}
      teacherId={state.teacherId} setTeacherId={state.setTeacherId}
      allTeachers={state.allTeachers} studentId={state.studentId} setStudentId={state.setStudentId}
      allStudents={state.allStudents} saveUser={state.saveUser}
      name={state.name} setName={state.setName} panelLogin={state.panelLogin}
      setPanelLogin={state.setPanelLogin} role={state.role} setRole={state.setRole}
      additionalInfo={state.additionalInfo} setAdditionalInfo={state.setAdditionalInfo}
      telegramId={state.telegramId} setTelegramId={state.setTelegramId}
      users={state.users} savingUser={state.savingUser}
      regeneratePanelAccessCode={state.regeneratePanelAccessCode}
      removeUser={state.removeUser} deleteCandidate={state.deleteCandidate}
      setDeleteCandidate={state.setDeleteCandidate} deletingUser={state.deletingUser}
      confirmRemoveUser={state.confirmRemoveUser}
      disconnectCandidate={state.disconnectCandidate}
      setDisconnectCandidate={state.setDisconnectCandidate}
      disconnectingTelegram={state.disconnectingTelegram}
      confirmDisconnectTelegram={state.confirmDisconnectTelegram}
      issuedCredential={state.issuedCredential} setIssuedCredential={state.setIssuedCredential}
      notify={notify} code={state.code} setCode={state.setCode}\n      unassignCandidate={state.unassignCandidate} setUnassignCandidate={state.setUnassignCandidate}\n      unassigningStudent={state.unassigningStudent} confirmUnassignStudent={state.confirmUnassignStudent}
    />
  </>;
}
