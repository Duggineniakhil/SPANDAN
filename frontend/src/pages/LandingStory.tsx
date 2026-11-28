/**
 * Landing page "inside the bearing": the part list and the exploding 3D bearing. three.js itself is
 * lazy-loaded, so this file is cheap for 2D devices.
 */
import { useScroll, useTransform } from "framer-motion";
import { lazy, Suspense, useRef, useState } from "react";
import { Reveal } from "../components/Motion";
import { BEARING_PARTS, type BearingPart } from "../three/parts";

const BearingExplode = lazy(() => import("../three/BearingExplode"));

/** Piecewise-linear map as a plain function (framer's hardware-accelerated scroll path skipped ranges). */
function ramp(input: number[], output: number[]) {
  return (v: number) => {
    if (v <= input[0]) return output[0];
    for (let i = 1; i < input.length; i++) {
      if (v <= input[i]) return output[i - 1] + ((output[i] - output[i - 1]) * (v - input[i - 1])) / (input[i] - input[i - 1]);
    }
    return output[output.length - 1];
  };
}

export function BearingSection({ use3D }: { use3D: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "center center"] });
  const explode = useTransform(scrollYProgress, ramp([0.3, 1], [0, 1]));
  const [hovered, setHovered] = useState<BearingPart | null>(null);
  return (
    <section className="section" ref={ref}>
      <div className="section-index mono"><span>03</span> INSIDE THE BEARING</div>
      <div className={use3D ? "split bearing-split" : ""}>
        <div>
          <Reveal><h2 className="h2">Each part fails at <span className="volt">its own frequency.</span></h2></Reveal>
          <p className="lead">
            The diagnosis is physics, not a black box. A pit on any part of a bearing makes impacts at a rate set by the
            bearing's geometry and the shaft speed. SPANDAN looks for exactly those, on a 6205 bearing at 2,880 rpm:
          </p>
          <ul className="part-list">
            {BEARING_PARTS.map((part) => (
              <li key={part.id} className={hovered === part.id ? "on" : ""}
                onMouseEnter={() => setHovered(part.id)} onMouseLeave={() => setHovered(null)}>
                <span className="part-name">{part.name}</span>
                <span className="mono volt">{part.freq}</span>
                <span className="part-note">{part.note}</span>
              </li>
            ))}
          </ul>
        </div>
        {use3D && (
          <Suspense fallback={<div className="bearing-canvas" />}>
            <BearingExplode explode={explode} hovered={hovered} onHover={setHovered} />
          </Suspense>
        )}
      </div>
    </section>
  );
}
