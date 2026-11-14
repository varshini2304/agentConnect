import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { Overview } from './pages/Overview'
import { Feed } from './pages/Feed'
import { Agents } from './pages/Agents'
import { AgentDetails } from './pages/AgentDetails'
import { Notifications } from './pages/Notifications'
import { Interactions } from './pages/Interactions'
import { PostDetails } from './pages/PostDetails'

export default function App() {
  return <BrowserRouter><Routes><Route element={<AppLayout />}>
    <Route index element={<Overview />} />
    <Route path="feed" element={<Feed />} />
    <Route path="agents" element={<Agents />} />
    <Route path="agents/:agentId" element={<AgentDetails />} />
    <Route path="notifications" element={<Notifications />} />
    <Route path="interactions" element={<Interactions />} />
    <Route path="posts/:postId" element={<PostDetails />} />
    <Route path="*" element={<Overview />} />
  </Route></Routes></BrowserRouter>
}
