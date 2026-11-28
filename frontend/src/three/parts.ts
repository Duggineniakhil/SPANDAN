/** The 6205 bearing's parts and fault frequencies at 2,880 rpm (48 Hz shaft); no three.js import. */
export type BearingPart = "outer" | "inner" | "balls" | "cage";

export const BEARING_PARTS: { id: BearingPart; name: string; fault: string; freq: string; note: string }[] = [
  { id: "outer", name: "Outer race", fault: "Outer-race wear", freq: "BPFO 172 Hz", note: "Fixed in the housing. Each ball rolls over a pit here 3.6 times per shaft turn." },
  { id: "balls", name: "9 balls", fault: "Ball damage", freq: "2×BSF 226 Hz", note: "A damaged ball strikes both races, twice per spin of the ball." },
  { id: "cage", name: "Cage", fault: "Cage wear", freq: "FTF 19 Hz", note: "Keeps the balls apart and turns at 0.4× shaft speed." },
  { id: "inner", name: "Inner race", fault: "Inner-race wear", freq: "BPFI 260 Hz", note: "Turns with the shaft, so a pit passes in and out of the load zone." },
];
