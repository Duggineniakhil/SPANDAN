import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Activity } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Landing from "./pages/Landing";
import Monitor from "./pages/Monitor";
import Setup from "./pages/Setup";

export default function App() {
  const location = useLocation();
  const onLanding = location.pathname === "/";
  const reduce = useReducedMotion();
  const [overHero, setOverHero] = useState(true);

  useEffect(() => {
    const onScroll = () => setOverHero(window.scrollY < window.innerHeight * 0.85);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      <nav className={`nav ${onLanding && overHero ? "nav-clear" : ""}`}>
        <NavLink to="/" className="brand">
          <Activity size={22} /> SPANDAN
        </NavLink>
        <div className="nav-links">
          <NavLink to="/setup">Setup</NavLink>
          <NavLink to="/monitor">Live monitor</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
        </div>
      </nav>
      {/* pages swing in from depth and tip away on the way out */}
      <div className="page-turn">
        <AnimatePresence mode="wait" initial={false} onExitComplete={() => window.scrollTo(0, 0)}>
          <motion.div key={location.pathname}
            initial={reduce ? { opacity: 0 } : { opacity: 0, rotateX: -10, y: 70, z: -160 }}
            animate={{ opacity: 1, rotateX: 0, y: 0, z: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, rotateX: 8, y: -40, z: -120 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
            <Routes location={location}>
              <Route path="/" element={<Landing />} />
              <Route path="/setup" element={<Setup />} />
              <Route path="/monitor" element={<Monitor />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="*" element={<Landing />} />
            </Routes>
          </motion.div>
        </AnimatePresence>
      </div>
    </>
  );
}
