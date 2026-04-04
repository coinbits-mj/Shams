import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getSession } from './api';
import Layout from './components/Layout';
import Login from './pages/Login';
import MissionControl from './pages/MissionControl';
import Today from './pages/Today';
import WarRoom from './pages/WarRoom';
import Memory from './pages/Memory';
import Loops from './pages/Loops';
import Decisions from './pages/Decisions';
import Briefings from './pages/Briefings';
import Files from './pages/Files';
import Mercury from './pages/Mercury';
import Money from './pages/Money';
import Deals from './pages/Deals';
import Projects from './pages/Projects';
import Delegations from './pages/Delegations';
import Integrations from './pages/Integrations';
import Conversations from './pages/Conversations';
import Actions from './pages/Actions';
import Inbox from './pages/Inbox';
import Settings from './pages/Settings';
import ToastProvider from './components/ToastProvider';

function ProtectedRoute({ children }) {
  return getSession() ? children : <Navigate to="/login" />;
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Today />} />
          <Route path="today" element={<Today />} />
          <Route path="missions" element={<MissionControl />} />
          <Route path="actions" element={<Actions />} />
          <Route path="inbox" element={<Inbox />} />
          {/* Chat is embedded in Mission Control sidebar */}
          <Route path="war-room" element={<WarRoom />} />
          <Route path="conversations" element={<Conversations />} />
          <Route path="memory" element={<Memory />} />
          <Route path="loops" element={<Loops />} />
          <Route path="decisions" element={<Decisions />} />
          <Route path="briefings" element={<Briefings />} />
          <Route path="files" element={<Files />} />
          <Route path="money" element={<Money />} />
          <Route path="deals" element={<Deals />} />
          <Route path="projects" element={<Projects />} />
          <Route path="delegations" element={<Delegations />} />
          <Route path="mercury" element={<Mercury />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
      </ToastProvider>
    </BrowserRouter>
  );
}
