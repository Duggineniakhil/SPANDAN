import { Activity } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import Landing from "./pages/Landing";
import Monitor from "./pages/Monitor";
import Setup from "./pages/Setup";

export default function App() {
  const onLanding = useLocation().pathname === "/";
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
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/setup" element={<Setup />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="*" element={<Landing />} />
      </Routes>
    </>
  );
}
