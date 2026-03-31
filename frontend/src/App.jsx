import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getSession } from './api';
import Layout from './components/Layout';
import Login from './pages/Login';
import MissionControl from './pages/MissionControl';
import Chat from './pages/Chat';
import WarRoom from './pages/WarRoom';
import Memory from './pages/Memory';
import Loops from './pages/Loops';
import Decisions from './pages/Decisions';
import Briefings from './pages/Briefings';
import Files from './pages/Files';
import Mercury from './pages/Mercury';
import Integrations from './pages/Integrations';
import Conversations from './pages/Conversations';

function ProtectedRoute({ children }) {
  return getSession() ? children : <Navigate to="/login" />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<MissionControl />} />
          <Route path="missions" element={<MissionControl />} />
          <Route path="chat" element={<Chat />} />
          <Route path="war-room" element={<WarRoom />} />
          <Route path="conversations" element={<Conversations />} />
          <Route path="memory" element={<Memory />} />
          <Route path="loops" element={<Loops />} />
          <Route path="decisions" element={<Decisions />} />
          <Route path="briefings" element={<Briefings />} />
          <Route path="files" element={<Files />} />
          <Route path="mercury" element={<Mercury />} />
          <Route path="integrations" element={<Integrations />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
