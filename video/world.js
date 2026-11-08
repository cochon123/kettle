/* Kettle — the film's 3D world: Margaret's house (with a kitchen you can see into) on a quiet street.
   Used by three moments: the plug in her kitchen (52–62 s), the street when Kettle asks Priya (76–92 s),
   and the flight back into her kitchen when the kettle comes on (92–102 s).
   Everything is a pure function of t, like film.js: WORLD.setup(t) places the camera and lights and
   returns screen anchors for the HTML labels, WORLD.draw() renders after film.js has drawn its 2D layers. */
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const W = 1920, H = 1080;
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, u) => a + (b - a) * u;
const ramp = (t, a, b) => clamp((t - a) / (b - a));
const io3 = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);
const ioSine = (x) => -(Math.cos(Math.PI * x) - 1) / 2;
const out3 = (x) => 1 - (1 - x) ** 3;
const er = (t, a, b, f = out3) => f(ramp(t, a, b));
function rng(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 16807) % 2147483647) / 2147483647); }
const KT = () => window.KTIME;
function wt(id, which) {   // voice-over word time, same as film.js
  const v = KT().vo.find((x) => x.id === String(id));
  const w = v.words.find((x) => x[0].toLowerCase().replace(/[^a-z0-9']/g, "").startsWith(which));
  return v.at + w[1];
}

// ------------------------------------------------------------------ renderer
const canvas = document.getElementById("gl");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;

const scene = new THREE.Scene();
const BG = new THREE.Color("#100b08");
scene.background = BG;
scene.fog = new THREE.FogExp2(BG, 0.018);
const camera = new THREE.PerspectiveCamera(32, W / H, 0.1, 400);

const hemi = new THREE.HemisphereLight("#6f80a4", "#2a1c12", 1.25);
scene.add(hemi);
const moon = new THREE.DirectionalLight("#b9c8e4", 2.1);
moon.position.set(-30, 46, 34);
moon.castShadow = true;
moon.shadow.mapSize.set(2048, 2048);
moon.shadow.bias = -0.0004;
moon.shadow.normalBias = 0.02;
scene.add(moon, moon.target);
function shadowBox(cx, cz, r) {
  const c = moon.shadow.camera;
  c.left = -r; c.right = r; c.top = r; c.bottom = -r; c.near = 1; c.far = 160;
  c.updateProjectionMatrix();
  moon.target.position.set(cx, 0, cz);
  moon.position.set(cx - 30, 46, cz + 34);
}

const composer = new EffectComposer(renderer);
composer.setPixelRatio(1);
composer.setSize(W, H);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(W / 2, H / 2), 0.7, 0.55, 0.86);
composer.addPass(bloom);
composer.addPass(new OutputPass());

// ------------------------------------------------------------------ materials + helpers
const mats = {};
const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0, ...o });
const glowTex = (() => {
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const x = c.getContext("2d"), g = x.createRadialGradient(128, 128, 0, 128, 128, 128);
  g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.25, "rgba(255,255,255,.55)"); g.addColorStop(0.6, "rgba(255,255,255,.12)"); g.addColorStop(1, "rgba(255,255,255,0)");
  x.fillStyle = g; x.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
})();
function box(w, h, d, mat, x = 0, y = 0, z = 0, parent, { cast = true, receive = true } = {}) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z); m.castShadow = cast; m.receiveShadow = receive;
  if (parent) parent.add(m);
  return m;
}
function cyl(rt, rb, h, mat, x, y, z, parent, seg = 20) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), mat);
  m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; parent.add(m); return m;
}
/** A soft additive light pool (on the ground) or halo (sprite). */
function pool(r, color, opacity, parent, x, y, z) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(r * 2, r * 2),
    new THREE.MeshBasicMaterial({ map: glowTex, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
  m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); m.renderOrder = 2; parent.add(m); return m;
}
function halo(r, color, opacity, parent, x, y, z) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
  s.scale.set(r * 2, r * 2, 1); s.position.set(x, y, z); s.renderOrder = 3; parent.add(s); return s;
}
const hot = (hex, k) => new THREE.Color(hex).multiplyScalar(k);
function emissive(color, k) { return new THREE.MeshBasicMaterial({ color: hot(color, k), toneMapped: false }); }

// ------------------------------------------------------------------ a house
/** Gable house, ridge parallel to the street, front facing +z. Returns its parts. */
function house({ w = 8, d = 7, h = 2.8, rise = 1.7, wall = "#4a3f37", roof = "#241c18", trim = "#2a221d", windows = [], door = -1.2, seed = 1, chimney = true, porch = true }) {
  const g = new THREE.Group(), t = 0.2, r = rng(seed);
  const wm = std(wall), rm = std(roof, { roughness: 0.75 }), tm = std(trim);
  const front = new THREE.Group(); g.add(front);
  box(w, 0.3, d, std("#2b231e"), 0, -0.012, 0, g);                                   // footing (top sits just under the kitchen floor: no z-fighting)
  box(w, h, t, wm, 0, h / 2, -d / 2 + t / 2, g);                                       // back
  box(t, h, d, wm, -w / 2 + t / 2, h / 2, 0, g); box(t, h, d, wm, w / 2 - t / 2, h / 2, 0, g);
  box(w, h, t, wm, 0, h / 2, d / 2 - t / 2, front);                                    // front wall (hidden in the cutaway)
  // gables
  const sh = new THREE.Shape([new THREE.Vector2(-d / 2, 0), new THREE.Vector2(d / 2, 0), new THREE.Vector2(0, rise)]);
  for (const sx of [-1, 1]) {
    const m = new THREE.Mesh(new THREE.ExtrudeGeometry(sh, { depth: t, bevelEnabled: false }), wm);
    m.rotation.y = Math.PI / 2; m.position.set(sx * (w / 2) - (sx > 0 ? t : 0), h, 0); m.castShadow = m.receiveShadow = true; g.add(m);
  }
  // roof slabs
  const th = Math.atan2(rise, d / 2), L = Math.hypot(d / 2, rise) + 0.5, ov = 0.35;
  const slabs = [];
  for (const sz of [1, -1]) {
    const m = box(w + ov * 2, 0.16, L, rm, 0, 0, 0, g);
    m.rotation.x = sz * th;
    m.position.set(0, h + rise - Math.sin(th) * L / 2 + Math.cos(th) * 0.09, sz * (Math.cos(th) * L / 2 + Math.sin(th) * 0.09));
    slabs.push(m);
  }
  box(w + ov * 2, 0.12, 0.12, tm, 0, h + rise + 0.1, 0, g);                             // ridge cap
  if (chimney) box(0.7, 1.6, 0.7, std("#3b2c25"), w * 0.28, h + rise * 0.8, -d * 0.18, g);
  // windows (planes on the front face) and the door
  const panes = [];
  for (const [wx, wy, ww, wh, lit] of windows) {
    const mat = lit ? emissive("#ffb46a", lit) : std("#161b26", { roughness: 0.25, metalness: 0.6 });
    const p = new THREE.Mesh(new THREE.PlaneGeometry(ww, wh), mat);
    p.position.set(wx, wy, d / 2 + 0.012); front.add(p); panes.push(p);
    box(ww + 0.16, 0.08, 0.14, tm, wx, wy - wh / 2 - 0.04, d / 2 + 0.05, front, { cast: false });   // sill
    box(ww + 0.12, 0.06, 0.06, tm, wx, wy + wh / 2 + 0.03, d / 2 + 0.02, front, { cast: false });
    box(0.05, wh, 0.05, tm, wx, wy, d / 2 + 0.03, front, { cast: false });                          // mullion
  }
  if (door !== null) {
    box(1.0, 2.1, 0.08, std("#5a2f22", { roughness: 0.6 }), door, 1.05 + 0.15, d / 2 + 0.03, front);
    box(0.08, 0.08, 0.05, std("#c9a56a", { metalness: 0.8, roughness: 0.3 }), door + 0.35, 1.15, d / 2 + 0.09, front, { cast: false });
    if (porch) box(1.6, 0.16, 1.0, std("#3a332d"), door, 0.08, d / 2 + 0.5, g);
  }
  g.userData = { w, d, h, rise, front, slabs, panes, frontSlab: slabs[0], door };
  return g;
}

function tree(x, z, s, r, parent) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(s);
  cyl(0.11, 0.16, 1.8, std("#2e2219"), 0, 0.9, 0, g, 7);
  const leaf = std(r() < 0.5 ? "#223024" : "#2a3626", { flatShading: true, roughness: 0.95 });
  const n = 2 + Math.floor(r() * 2);
  for (let i = 0; i < n; i++) {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.9 + r() * 0.5, 0), leaf);
    m.position.set((r() - 0.5) * 0.9, 2.1 + i * 0.6 + r() * 0.3, (r() - 0.5) * 0.9);
    m.rotation.set(r() * 3, r() * 3, r() * 3); m.castShadow = m.receiveShadow = true; g.add(m);
  }
  parent.add(g); return g;
}
function car(x, z, rot, color, parent) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rot;
  const body = new THREE.Mesh(new RoundedBoxGeometry(4.2, 0.8, 1.8, 3, 0.25), std(color, { roughness: 0.35, metalness: 0.5 }));
  body.position.y = 0.65; body.castShadow = body.receiveShadow = true; g.add(body);
  const cab = new THREE.Mesh(new RoundedBoxGeometry(2.3, 0.7, 1.6, 3, 0.22), std("#141922", { roughness: 0.15, metalness: 0.7 }));
  cab.position.set(-0.2, 1.25, 0); cab.castShadow = true; g.add(cab);
  for (const [wx, wz] of [[1.35, 0.85], [-1.35, 0.85], [1.35, -0.85], [-1.35, -0.85]]) {
    const wh = cyl(0.36, 0.36, 0.26, std("#0d0d0d"), wx, 0.36, wz, g, 14); wh.rotation.x = Math.PI / 2;
  }
  parent.add(g); return g;
}
function lamp(x, z, side, parent) {
  const g = new THREE.Group(); g.position.set(x, 0, z);
  const pm = std("#1c1a19", { roughness: 0.5, metalness: 0.4 });
  cyl(0.07, 0.09, 5.2, pm, 0, 2.6, 0, g, 8);
  const arm = box(0.08, 0.08, 1.2, pm, 0, 5.15, side * 0.55, g); arm.castShadow = false;
  box(0.36, 0.12, 0.5, pm, 0, 5.1, side * 1.1, g);
  const bulb = box(0.26, 0.04, 0.38, emissive("#ffc98a", 4), 0, 5.03, side * 1.1, g, { cast: false });
  pool(5.5, "#ffb060", 0.22, g, 0, 0.03, side * 1.1);
  halo(0.9, "#ffc078", 0.5, g, 0, 4.98, side * 1.1);
  parent.add(g); return { g, bulb };
}

// ------------------------------------------------------------------ the street
const world = new THREE.Group(); scene.add(world);
const r0 = rng(11);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), std("#16120f", { roughness: 1 }));
ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; world.add(ground);
const flat = (w, d, color, x, z, y = 0.01, o = {}) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), std(color, o)); m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); m.receiveShadow = true; world.add(m); return m; };
const STREET_Z = 13, SW = 8;                          // street centre line, width
flat(220, 60, "#1a1d15", 0, -12, 0.005);              // lawns, north
flat(220, 40, "#1a1d15", 0, STREET_Z + 22, 0.005);    // lawns, south
flat(220, SW, "#121110", 0, STREET_Z, 0.02, { roughness: 0.9 });                // asphalt
for (let x = -110; x < 110; x += 6) flat(2.6, 0.16, "#5d564b", x, STREET_Z, 0.025);
for (const sz of [-1, 1]) {
  flat(220, 1.6, "#3a352f", 0, STREET_Z + sz * (SW / 2 + 1.0), 0.03);          // sidewalks
  const c = box(220, 0.14, 0.18, std("#4a443c"), 0, 0.07, STREET_Z + sz * (SW / 2 + 0.09), world, { cast: false });
}
const homes = {};
const PAL = [["#4b4038", "#231b17"], ["#3e3a36", "#1f1c1c"], ["#52463b", "#2a1f19"], ["#3a3631", "#26201d"], ["#46413c", "#1d1916"], ["#4d4239", "#2b221c"]];
function addHome(id, x, south, o = {}) {
  const r = rng(Math.round(x * 7 + (south ? 1000 : 0)) + 5);
  const p = PAL[Math.floor(r() * PAL.length)];
  const w = o.w || 7.4 + r() * 1.6, d = o.d || 6.6 + r() * 1.0, h = o.h || 2.7 + (r() < 0.25 ? 2.6 : r() * 0.3);
  const lit = () => (r() < 0.42 ? 0.9 + r() * 0.8 : 0);
  const windows = o.windows || [[-w * 0.32, 1.45, 1.3, 1.1, lit()], [w * 0.22, 1.45, 1.7, 1.1, lit()], ...(h > 4 ? [[-w * 0.2, 3.9, 1.2, 1.0, lit()], [w * 0.24, 3.9, 1.2, 1.0, lit()]] : [])];
  const g = house({ w, d, h, rise: o.rise || 1.4 + r() * 0.7, wall: o.wall || p[0], roof: o.roof || p[1], windows, door: o.door ?? (r() < 0.5 ? -w * 0.05 : w * 0.02), seed: r() * 1e6, chimney: r() < 0.6, ...o });
  g.position.set(x, 0, south ? STREET_Z + SW / 2 + 1.8 + 3.5 + d / 2 - 0.5 : STREET_Z - SW / 2 - 1.8 - 3.5 - d / 2 + 0.5);
  if (south) g.rotation.y = Math.PI;
  world.add(g); homes[id] = g;
  if (o.zOff) { g.position.z += o.zOff; tree(x + w * 0.6, g.position.z - d / 2 - 3, 1 + r() * 0.4, r, world); return g; }
  // front walk + driveway
  const dz = south ? -1 : 1, fz = g.position.z + dz * (d / 2), sz = STREET_Z - dz * (SW / 2 + 1.8);
  const doorX = x + (south ? -1 : 1) * g.userData.door;
  flat(1.1, Math.abs(sz - fz), "#3a342e", doorX, (fz + sz) / 2, 0.028);
  if (r() < 0.6 || o.car) { const dx = x + (south ? -1 : 1) * (w / 2 + 1.6); flat(3.0, Math.abs(sz - fz) + 2, "#2c2925", dx, (fz + sz) / 2 - dz, 0.027); if (o.car !== false && r() < 0.55) car(dx, (fz + sz) / 2 - dz * 0.5, Math.PI / 2, ["#5a2b24", "#2b3a4c", "#6b6a66", "#23262b"][Math.floor(r() * 4)], world); }
  for (let i = 0; i < 2; i++) if (r() < 0.7) tree(x + (r() - 0.5) * w * 1.1, g.position.z + (south ? 1 : -1) * (d / 2 + 2.5 + r() * 4), 0.9 + r() * 0.5, r, world);
  return g;
}
// Margaret's house is built with an interior (below); the neighbours are plain.
const MARG_X = 0;
const marg = house({ w: 8, d: 7, h: 2.8, rise: 1.75, wall: "#5a4a3e", roof: "#2a1f1a", trim: "#33281f", door: -1.4, seed: 3,
  windows: [[-3.0, 1.55, 1.4, 1.1, 0], [1.9, 1.55, 2.0, 1.1, 0]] });
marg.position.set(MARG_X, 0, STREET_Z - SW / 2 - 1.8 - 3.5 - 3.5 + 0.5);
world.add(marg); homes.margaret = marg;
{
  const fz = marg.position.z + 3.5, sz = STREET_Z - (SW / 2 + 1.8);
  flat(1.1, sz - fz, "#3a342e", MARG_X - 1.4, (fz + sz) / 2, 0.028);
  tree(-5.5, marg.position.z - 6, 1.25, rng(4), world); tree(9.0, marg.position.z - 6.5, 0.9, rng(9), world);
}
for (const x of [-48, -36, -24, -12]) addHome("n" + x, x, false);
addHome("priya", 12, false, { wall: "#4f4339", roof: "#26201b", door: -1.2, car: true, windows: [[-2.6, 1.45, 1.3, 1.1, 1.5], [1.9, 1.45, 1.7, 1.1, 1.2]] });
for (const x of [24, 36, 48]) addHome("n" + x, x, false);
for (const x of [-42, -30, -18, 6, 18, 30, 42]) addHome("s" + x, x, true);
addHome("tom", -6, true, { wall: "#3f3c37", roof: "#1e1b1a", door: 0.4, windows: [[-2.4, 1.45, 1.3, 1.1, 1.2], [2.2, 1.45, 1.6, 1.1, 0]] });
// back rows, for depth from above
for (let x = -54; x <= 54; x += 12) addHome("b" + x, x + 3, false, { car: false, zOff: -21 });
const lamps = [];
for (const x of [-38, -17, 18, 40]) lamps.push(lamp(x, STREET_Z - SW / 2 - 0.4, 1, world));
for (let x = -33; x <= 44; x += 22) lamps.push(lamp(x, STREET_Z + SW / 2 + 0.4, -1, world));
car(-15, STREET_Z + 2.4, 0, "#3b4a5a", world);
car(28, STREET_Z - 2.4, Math.PI, "#6a5d52", world);

// ------------------------------------------------------------------ Margaret's kitchen (house-local coordinates)
const I = new THREE.Group(); marg.add(I);
const FL = 0.15;                                                            // floor top
box(7.6, 0.06, 6.6, std("#5b4232", { roughness: 0.7 }), 0, FL - 0.03, 0, I, { cast: false });
for (let i = -3; i <= 3; i++) box(7.6, 0.004, 0.012, std("#46322a"), 0, FL + 0.005, i * 0.9, I, { cast: false }); // planks
box(7.58, 2.6, 0.02, std("#d9c7ae", { roughness: 0.95 }), 0, FL + 1.3, -3.29, I, { cast: false });          // inner back wall paint
box(0.02, 2.6, 6.6, std("#b5a28b", { roughness: 0.95 }), -3.79, FL + 1.3, 0, I, { cast: false });
box(0.02, 2.6, 6.6, std("#b5a28b", { roughness: 0.95 }), 3.79, FL + 1.3, 0, I, { cast: false });
const CAB = std("#3f5249", { roughness: 0.6 }), TOP = std("#d8cfc2", { roughness: 0.35 }), HANDLE = std("#b9a27a", { metalness: 0.9, roughness: 0.3 });
const CT = FL + 0.88;                                                        // counter top surface
box(3.5, 0.86, 0.62, CAB, 2.0, FL + 0.43, -2.98, I);
for (let i = 0; i < 4; i++) { box(0.012, 0.8, 0.005, std("#26332d"), 0.25 + 0.875 * (i + 1) - 0.0, FL + 0.43, -2.665, I, { cast: false }); box(0.18, 0.025, 0.03, HANDLE, 0.69 + 0.875 * i, FL + 0.74, -2.65, I, { cast: false }); }
box(3.56, 0.04, 0.66, TOP, 2.0, CT - 0.02, -2.97, I);
box(3.5, 0.62, 0.02, std("#e6dccd", { roughness: 0.4 }), 2.0, CT + 0.31, -3.27, I, { cast: false });       // backsplash
// window over the counter: pale morning light
const winGlass = new THREE.Mesh(new THREE.PlaneGeometry(1.15, 0.95), new THREE.MeshBasicMaterial({ color: hot("#9fb8d8", 1.1), toneMapped: false }));
winGlass.position.set(1.95, CT + 1.05, -3.275); I.add(winGlass);
for (const [w, h, x, y] of [[1.27, 0.06, 1.95, CT + 0.55], [1.27, 0.06, 1.95, CT + 1.55], [0.06, 1.0, 1.35, CT + 1.05], [0.06, 1.0, 2.55, CT + 1.05], [0.04, 0.95, 1.95, CT + 1.05]]) box(w, h, 0.05, std("#efe7da"), x, y, -3.25, I, { cast: false });
box(0.45, 0.7, 0.34, CAB, 0.48, CT + 1.05, -3.1, I); box(0.95, 0.7, 0.34, CAB, 3.2, CT + 1.05, -3.1, I);
// the kettle
const KET = new THREE.Group(); KET.position.set(1.05, CT, -2.93); I.add(KET);
{
  const prof = [[0, 0.02], [0.074, 0.02], [0.082, 0.03], [0.086, 0.08], [0.084, 0.15], [0.074, 0.205], [0.056, 0.232], [0.03, 0.24], [0, 0.242]].map(([a, b]) => new THREE.Vector2(a, b));
  const enamel = std("#ece4d6", { roughness: 0.28, metalness: 0.05 });
  const body = new THREE.Mesh(new THREE.LatheGeometry(prof, 48), enamel); body.castShadow = body.receiveShadow = true; KET.add(body);
  cyl(0.094, 0.098, 0.022, std("#1e1915", { roughness: 0.5 }), 0, 0.011, 0, KET, 40);                    // base
  const knob = cyl(0.018, 0.022, 0.022, std("#2a211b"), 0, 0.252, 0, KET, 16);
  const handle = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([V(-0.07, 0.205, 0), V(-0.13, 0.2, 0), V(-0.15, 0.13, 0), V(-0.12, 0.06, 0), V(-0.082, 0.045, 0)]), 32, 0.013, 10), std("#2a211b", { roughness: 0.45 }));
  handle.castShadow = true; KET.add(handle);
  const spout = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.024, 0.11, 16, 1, true), enamel);
  spout.position.set(0.098, 0.165, 0); spout.rotation.z = -0.95; spout.castShadow = true; KET.add(spout);
  KET.userData.spoutTip = V(0.142, 0.2, 0);
}
const kLedMat = new THREE.MeshBasicMaterial({ color: hot("#ffb457", 0.15), toneMapped: false });
const kLed = new THREE.Mesh(new THREE.TorusGeometry(0.095, 0.0035, 8, 64), kLedMat); kLed.rotation.x = Math.PI / 2; kLed.position.y = 0.018; KET.add(kLed);
const kSwitch = box(0.018, 0.012, 0.03, kLedMat, -0.118, 0.052, 0, KET, { cast: false });
const kLight = new THREE.PointLight("#ffb56a", 0, 1.6, 2); kLight.position.set(1.05, CT + 0.3, -2.45); I.add(kLight);
const kHalo = halo(0.22, "#ffb457", 0, I, 1.05, CT + 0.02, -2.9);
// the smart plug in the wall outlet, and the cord
box(0.09, 0.13, 0.012, std("#efe8dc"), 0.48, CT + 0.2, -3.255, I, { cast: false });
const plug = new THREE.Mesh(new RoundedBoxGeometry(0.075, 0.085, 0.045, 3, 0.014), std("#f3eee6", { roughness: 0.4 }));
plug.position.set(0.48, CT + 0.2, -3.225); plug.castShadow = true; I.add(plug);
const pLedMat = new THREE.MeshBasicMaterial({ color: hot("#ffb457", 0.3), toneMapped: false });
const pLed = new THREE.Mesh(new THREE.SphereGeometry(0.0065, 12, 8), pLedMat); pLed.position.set(0.48, CT + 0.228, -3.2); I.add(pLed);
const pHalo = halo(0.08, "#ffb457", 0, I, 0.48, CT + 0.228, -3.19);
I.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([V(0.96, CT + 0.012, -2.93), V(0.8, CT + 0.008, -3.05), V(0.6, CT + 0.01, -3.18), V(0.49, CT + 0.07, -3.21), V(0.48, CT + 0.155, -3.215)]), 40, 0.0045, 8), std("#e9e2d6", { roughness: 0.5 })));
// the Kettle hub: a small display on a stand
const HUB = new THREE.Group(); HUB.position.set(2.85, CT, -2.86); HUB.rotation.y = -0.32; I.add(HUB);
box(0.06, 0.012, 0.12, std("#1c1714"), 0, 0.006, 0, HUB);
const stand = box(0.03, 0.17, 0.02, std("#1c1714"), 0, 0.09, -0.025, HUB); stand.rotation.x = -0.25;
const hubFrame = new THREE.Mesh(new RoundedBoxGeometry(0.34, 0.22, 0.016, 3, 0.012), std("#0c0907", { roughness: 0.4 }));
hubFrame.position.set(0, 0.17, 0.0); hubFrame.rotation.x = -0.22; hubFrame.castShadow = true; HUB.add(hubFrame);
const hubScreenMat = new THREE.MeshBasicMaterial({ color: hot("#ffffff", 0.9), toneMapped: false });
const hubScreen = new THREE.Mesh(new THREE.PlaneGeometry(0.315, 0.197), hubScreenMat);
hubScreen.position.set(0, 0.17 + 0.0018, 0.0087); hubScreen.rotation.x = -0.22; HUB.add(hubScreen);
const hubGlow = new THREE.PointLight("#ffb46a", 0, 2.4, 1.8); hubGlow.position.set(2.8, CT + 0.25, -2.55); I.add(hubGlow);
// a mug, a plant, a pendant lamp
{ const mm = std("#2f4e63", { roughness: 0.35 }); cyl(0.04, 0.037, 0.095, mm, 1.42, CT + 0.0475, -2.86, I, 24);
  const mh = new THREE.Mesh(new THREE.TorusGeometry(0.026, 0.007, 8, 20, Math.PI * 1.2), mm); mh.position.set(1.465, CT + 0.05, -2.86); mh.rotation.z = -Math.PI * 0.6; I.add(mh); }
cyl(0.07, 0.055, 0.12, std("#a0573a"), 2.4, CT + 0.06, -3.05, I, 16);
for (let i = 0; i < 5; i++) { const lf = new THREE.Mesh(new THREE.IcosahedronGeometry(0.06, 0), std("#3d5a35", { flatShading: true })); lf.position.set(2.4 + Math.cos(i * 1.3) * 0.05, CT + 0.17 + (i % 2) * 0.05, -3.05 + Math.sin(i * 1.3) * 0.05); I.add(lf); }
cyl(0.004, 0.004, 0.9, std("#111"), 1.95, FL + 2.15, -2.5, I, 6);
const shade = cyl(0.09, 0.2, 0.18, std("#2a2420", { side: THREE.DoubleSide }), 1.95, FL + 1.62, -2.5, I, 24);
const bulbMat = new THREE.MeshBasicMaterial({ color: hot("#ffcf8f", 2.5), toneMapped: false });
const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 10), bulbMat); bulb.position.set(1.95, FL + 1.53, -2.5); I.add(bulb);
const roomLight = new THREE.PointLight("#ffc488", 0, 9, 1.4); roomLight.position.set(1.95, FL + 1.45, -2.2); I.add(roomLight);
// living corner: armchair, floor lamp, rug, a framed photo
const chair = new THREE.Group(); chair.position.set(-2.2, FL, -1.5); chair.rotation.y = 0.6; I.add(chair);
const fab = std("#7a4a3a", { roughness: 0.95 });
box(0.9, 0.42, 0.85, fab, 0, 0.21, 0, chair); box(0.9, 0.75, 0.2, fab, 0, 0.6, -0.33, chair); box(0.18, 0.55, 0.85, fab, -0.42, 0.42, 0, chair); box(0.18, 0.55, 0.85, fab, 0.42, 0.42, 0, chair);
box(2.4, 0.012, 1.7, std("#6b5a48", { roughness: 1 }), -2.0, FL + 0.006, -0.9, I, { cast: false });
cyl(0.015, 0.015, 1.5, std("#1a1614"), -3.3, FL + 0.75, -2.7, I, 8);
const fl = cyl(0.12, 0.2, 0.26, new THREE.MeshBasicMaterial({ color: hot("#ffc683", 1.3), toneMapped: false, side: THREE.DoubleSide }), -3.3, FL + 1.55, -2.7, I, 24);
const floorLamp = new THREE.PointLight("#ffbe7a", 0, 5, 1.6); floorLamp.position.set(-3.3, FL + 1.35, -2.5); I.add(floorLamp);
box(1.4, 1.8, 0.32, std("#3a2a20"), -1.5, FL + 0.9, -3.12, I);                                             // bookshelf
for (let i = 0; i < 3; i++) for (let j = 0; j < 7; j++) { const r = rng(i * 13 + j); box(0.08 + r() * 0.06, 0.24 + r() * 0.08, 0.2, std(["#6b3b2e", "#2f4a58", "#8a7350", "#4d5a3a"][Math.floor(r() * 4)]), -2.05 + j * 0.17, FL + 0.32 + i * 0.58, -3.08, I, { cast: false }); }
box(0.03, 0.38, 0.5, std("#2a1f18"), -3.775, FL + 1.65, -0.9, I, { cast: false });
box(0.01, 0.3, 0.42, std("#b99d7c"), -3.755, FL + 1.65, -0.9, I, { cast: false });

// the walls glow when "the raw readings never leave her home": bright edges around the shell
const shell = new THREE.Group(); marg.add(shell);
{
  const { w, d, h, rise } = marg.userData, e = 0.018;
  const P = (x, y, z) => V(x, y, z);
  const segs = [];
  const c = [P(-w / 2, 0.15, -d / 2), P(w / 2, 0.15, -d / 2), P(w / 2, 0.15, d / 2), P(-w / 2, 0.15, d / 2)];
  const top = c.map((p) => P(p.x, h, p.z));
  for (let i = 0; i < 4; i++) { segs.push([c[i], c[(i + 1) % 4]], [top[i], top[(i + 1) % 4]], [c[i], top[i]]); }
  const rL = P(-w / 2, h + rise, 0), rR = P(w / 2, h + rise, 0);
  segs.push([rL, rR], [top[0], rL], [top[3], rL], [top[1], rR], [top[2], rR]);
  const m = new THREE.MeshBasicMaterial({ color: hot("#ffb457", 1.25), toneMapped: false, transparent: true, opacity: 0 });
  for (const [a, b] of segs) {
    const len = a.distanceTo(b), mesh = new THREE.Mesh(new THREE.CylinderGeometry(e, e, len, 6), m);
    mesh.position.copy(a).add(b).multiplyScalar(0.5);
    mesh.quaternion.setFromUnitVectors(V(0, 1, 0), b.clone().sub(a).normalize());
    shell.add(mesh);
  }
  shell.userData.mat = m;
  shell.userData.pool = pool(9, "#ffa850", 0, marg, 0, 0.04, 0);
}
// Margaret's alarm: a soft pulse around the house, from the street
const margPool = pool(10, "#ffa850", 0, marg, 0, 0.05, 2.5);
const margHalo = halo(4.5, "#ffb060", 0, marg, 0, 5.4, 0);
const margWin = marg.userData.panes;
for (const p of margWin) { p.material = new THREE.MeshBasicMaterial({ color: new THREE.Color(), toneMapped: false, transparent: true }); p.material.userData.faded = true; }

// ------------------------------------------------------------------ the route: Priya's door → Margaret's door
const priya = homes.priya, tom = homes.tom;
const sideZ = STREET_Z - SW / 2 - 0.9;
const pDoor = V(priya.position.x + priya.userData.door, 0.06, priya.position.z + priya.userData.d / 2 + 0.6);
const mDoor = V(MARG_X - 1.4, 0.06, marg.position.z + 3.5 + 1.1);
const route = new THREE.CurvePath();
const rr = 0.9;
route.add(new THREE.LineCurve3(pDoor, V(pDoor.x, 0.06, sideZ - rr)));
route.add(new THREE.QuadraticBezierCurve3(V(pDoor.x, 0.06, sideZ - rr), V(pDoor.x, 0.06, sideZ), V(pDoor.x - rr, 0.06, sideZ)));
route.add(new THREE.LineCurve3(V(pDoor.x - rr, 0.06, sideZ), V(mDoor.x + rr, 0.06, sideZ)));
route.add(new THREE.QuadraticBezierCurve3(V(mDoor.x + rr, 0.06, sideZ), V(mDoor.x, 0.06, sideZ), V(mDoor.x, 0.06, sideZ - rr)));
route.add(new THREE.LineCurve3(V(mDoor.x, 0.06, sideZ - rr), mDoor));
// even spacing along the whole path
const routePts = route.getSpacedPoints(600);
const routeCurve = new THREE.CatmullRomCurve3(routePts, false, "catmullrom", 0.0);
const TUBE_SEG = 600, TUBE_RAD = 8;
const routeGeo = new THREE.TubeGeometry(routeCurve, TUBE_SEG, 0.075, TUBE_RAD, false);
const routeMat = new THREE.MeshBasicMaterial({ color: hot("#ffc47a", 2.4), toneMapped: false, transparent: true, opacity: 1 });
const routeMesh = new THREE.Mesh(routeGeo, routeMat); routeMesh.renderOrder = 4; world.add(routeMesh);
const routeHead = halo(0.9, "#ffc47a", 0, world, 0, 0.3, 0);
const walker = halo(0.8, "#ffffff", 0, world, 0, 0.5, 0), walkerHalo = halo(2.4, "#ffb457", 0, world, 0, 0.5, 0);
const priyaPool = pool(4.5, "#ffb457", 0, priya, 0, 0.05, priya.userData.d / 2 + 1.5);

// ------------------------------------------------------------------ the chip that leaves the house
const chipGlow = halo(0.5, "#ffb457", 0, marg, 0, 0, 0);

// ------------------------------------------------------------------ hub screen textures
const loader = new THREE.TextureLoader();
const tex = {};
async function loadTex(k, url) { const t = await loader.loadAsync(url); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; tex[k] = t; }
// the raw-readings trace, drawn by film.js into #se-wave, floats above the counter
const waveTex = new THREE.CanvasTexture(document.getElementById("se-wave"));
waveTex.colorSpace = THREE.SRGBColorSpace;
const wavePlane = new THREE.Mesh(new THREE.PlaneGeometry(3.4, 1.21), new THREE.MeshBasicMaterial({ map: waveTex, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false, color: hot("#ffffff", 1.6) }));
wavePlane.position.set(0.3, 2.05, 0.4); wavePlane.renderOrder = 5; marg.add(wavePlane);

// ------------------------------------------------------------------ camera paths
const local = (v) => marg.localToWorld(v.clone());
const K = () => local(KET.position.clone());
function spline(keys, t) {   // keys: [[t, pos, target, fov, offX]], centripetal Catmull-Rom through pos/target, eased per segment
  if (t <= keys[0][0]) return keys[0];
  const n = keys.length;
  if (t >= keys[n - 1][0]) return keys[n - 1];
  let i = 0; while (t > keys[i + 1][0]) i++;
  const u = ioSine(ramp(t, keys[i][0], keys[i + 1][0]));
  const pick = (j) => keys[clamp(j, 0, n - 1)];
  const cr = (k) => new THREE.CatmullRomCurve3([pick(i - 1)[k], pick(i)[k], pick(i + 1)[k], pick(i + 2)[k]], false, "centripetal").getPoint((1 + u) / 3);
  return [t, cr(1), cr(2), lerp(keys[i][3], keys[i + 1][3], u), lerp(keys[i][4], keys[i + 1][4], u)];
}
let SENSE = null, STREET = null, DIVE = null;
function buildPaths() {
  const k = K(), hub = local(V(2.85, CT + 0.17, -2.86)), M = marg.position;
  SENSE = [
    [52.0, k.clone().add(V(0.42, 0.2, 1.05)), k.clone().add(V(-0.12, 0.08, 0)), 30, 0],
    [54.6, k.clone().add(V(1.15, 0.42, 2.25)), k.clone().add(V(0.7, 0.12, -0.1)), 32, 0],
    [57.6, M.clone().add(V(2.6, 3.4, 12.5)), M.clone().add(V(0.6, 1.3, -1.0)), 34, 0],
    [62.2, M.clone().add(V(4.6, 5.8, 15.5)), M.clone().add(V(0.4, 1.7, -0.8)), 34, 0],
  ];
  STREET = [
    [76.4, M.clone().add(V(-3, 42, 50)), M.clone().add(V(3, 0, 10.5)), 30, 0],
    [83.3, M.clone().add(V(-1, 35, 43)), M.clone().add(V(3.5, 0, 10)), 30, 0],
    [84.6, M.clone().add(V(-1.5, 34, 42)), M.clone().add(V(2.4, 0, 11)), 32, 330],
    [92.3, M.clone().add(V(-0.5, 29, 37)), M.clone().add(V(2.4, 0, 10)), 32, 330],
  ];
  DIVE = [
    [92.3, STREET[3][1], STREET[3][2], 32, 330],
    [93.2, M.clone().add(V(-0.5, 5.2, 15)), M.clone().add(V(0.4, 1.6, 0)), 34, 330],
    [93.9, M.clone().add(V(0.8, 1.9, 4.6)), k.clone().add(V(-0.1, 0.25, 0)), 36, 330],
    [94.5, k.clone().add(V(0.62, 0.5, 2.1)), k.clone().add(V(0.12, 0.12, 0)), 30, 330],
    [101.8, k.clone().add(V(0.44, 0.42, 1.7)), k.clone().add(V(0.08, 0.12, 0)), 30, 330],
  ];
}

// ------------------------------------------------------------------ per frame
const proj = (v) => { const p = v.clone().project(camera); return [(p.x + 1) / 2 * W, (1 - p.y) / 2 * H, p.z]; };
let active = false;
function setCam(k) {
  camera.position.copy(k[1]); camera.lookAt(k[2]); camera.fov = k[3];
  if (k[4]) camera.setViewOffset(W, H, k[4], 0, W, H); else camera.clearViewOffset();
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}
function setup(t) {
  const inSense = t > 52.0 && t < 62.4, inStreet = t > 76.2 && t < 102;
  active = inSense || inStreet;
  const op = inSense ? ioSine(ramp(t, 52.05, 52.9)) * (1 - ramp(t, 61.5, 62.3)) : inStreet ? ramp(t, 76.3, 77.6) * (1 - ramp(t, 100.9, 101.9)) : 0;
  canvas.style.opacity = op.toFixed(3);
  canvas.style.visibility = op > 0.001 ? "visible" : "hidden";
  if (!active || op <= 0.001) { active = false; return null; }
  const A = {};
  // defaults
  const front = marg.userData.front, fSlab = marg.userData.frontSlab;
  let cut = 0, interior = 0, kettleOn = 0, plugLit = 0, hubAsk = 0, wall = 0, wave = 0, chip = -1, alarm = 0, thread = 0, go = 0, members = 0;
  scene.fog.density = inSense || t > 93.2 ? 0.02 : 0.0065;
  if (inSense) {
    shadowBox(marg.position.x, marg.position.z, 12);
    setCam(spline(SENSE, t));
    cut = 1; interior = 1;
    plugLit = er(t, wt(9, "plug") - 0.1, wt(9, "plug") + 0.4);
    wave = er(t, wt(9, "the") - 0.2, wt(9, "the") + 0.8) * (1 - er(t, 61.0, 61.8));
    wall = er(t, wt(9, "never"), wt(9, "never") + 0.6) * (1 - er(t, wt(9, "only") + 0.4, wt(9, "only") + 1.4));
    chip = ramp(t, wt(9, "only") - 0.2, wt(9, "kettle") + 1.6);
  } else {
    const diving = t >= 92.3;
    shadowBox(diving ? marg.position.x : 6, diving ? marg.position.z : 6, diving ? 14 : 40);
    setCam(diving ? spline(DIVE, t) : spline(STREET, t));
    cut = er(t, 92.9, 93.7, io3);
    interior = 0.25 + 0.75 * cut;
    alarm = er(t, 76.6, 77.6) * (1 - er(t, 92.6, 93.4));
    members = er(t, wt(13, "it") + 0.5, wt(13, "it") + 1.6);
    thread = er(t, wt(14, "priya") - 0.1, wt(14, "priya") + 1.6, io3);
    go = er(t, 88.6, 92.4, ioSine);
    kettleOn = t >= 94.42 ? 1 : 0;
    hubAsk = 1 - kettleOn;
    plugLit = 0.4 + 0.6 * kettleOn;
  }
  // cutaway: front wall and front roof slab fade out
  for (const m of [...front.children.filter((c) => c.isMesh), fSlab]) {
    m.visible = cut < 0.999 && !(margWin.includes(m) && t > 92.95);
    if (!m.material.userData.faded) { m.material = m.material.clone(); m.material.userData.faded = true; m.material.transparent = true; m.material.needsUpdate = true; }
    m.material.opacity = margWin.includes(m) ? (inSense ? 0 : 1 - er(t, 92.45, 92.95)) : 1 - cut; m.material.depthWrite = cut < 0.5;
    m.castShadow = cut < 0.5;
  }
  I.visible = inSense || cut > 0.001;
  // interior light: warm for the explainer, quiet grey morning in the story until the kettle clicks
  const on = inSense ? 1 : kettleOn ? er(t, 94.42, 96.5) : 0;
  roomLight.intensity = inSense ? 1.7 : 0.3 + 1.2 * on;
  bulbMat.color.copy(hot("#ffcf8f", inSense ? 2.5 : 0.25 + 2.3 * on));
  floorLamp.intensity = inSense ? 0.9 : 0.12 + 0.7 * on;
  fl.material.color.copy(hot("#ffc683", inSense ? 1.3 : 0.2 + 1.1 * on));
  const flash = kettleOn ? Math.exp(-(t - 94.42) * 3) : 0;
  kLedMat.color.copy(hot("#ffb457", 0.12 + (inSense ? 0 : kettleOn) * (1.6 + 1.4 * flash)));
  kLight.intensity = kettleOn ? 0.18 + 0.4 * flash : 0;
  kHalo.material.opacity = kettleOn ? 0.16 + 0.25 * flash : 0;
  pLedMat.color.copy(hot("#ffb457", 0.3 + 2.6 * plugLit));
  pHalo.material.opacity = 0.6 * plugLit;
  // hub screen: the "I'm fine" check-in glows until the kettle answers it
  const pulse = 0.5 + 0.5 * Math.sin((t - 67) * 3.4);
  const want = hubAsk > 0.5 ? tex.ask : tex.morning;
  if (hubScreenMat.map !== want) { hubScreenMat.map = want; hubScreenMat.needsUpdate = true; }
  hubScreenMat.color.copy(hot("#ffffff", hubAsk > 0.5 ? 0.9 + 0.35 * pulse : 0.85));
  hubGlow.intensity = hubAsk > 0.5 ? (0.6 + 0.5 * pulse) * interior : 0.35;
  // street: Margaret's windows breathe amber while Kettle waits for her
  for (const p of margWin) p.material.color.copy(hot("#ffa04a", inSense ? 1.6 : 0.25 + alarm * (1.6 + 1.6 * pulse) + 1.6 * on));
  margPool.material.opacity = alarm * (0.45 + 0.3 * pulse);
  margHalo.material.opacity = alarm * (0.12 + 0.1 * pulse);
  shell.userData.mat.opacity = wall;
  shell.userData.pool.material.opacity = 0.35 * wall;
  wavePlane.material.opacity = wave;
  wavePlane.quaternion.copy(camera.quaternion); marg.updateMatrixWorld();
  { const q = new THREE.Quaternion(); marg.getWorldQuaternion(q); wavePlane.quaternion.premultiply(q.invert()); }
  waveTex.needsUpdate = wave > 0;
  // route + walker
  routeMesh.visible = thread > 0.001;
  const idx = Math.floor(routeGeo.index.count * thread / 6) * 6;
  routeGeo.setDrawRange(0, idx);
  routeMat.opacity = 1 - er(t, 92.4, 93.0);
  const head = routeCurve.getPointAt(clamp(thread, 0, 1));
  routeHead.position.copy(head).setY(0.35); routeHead.material.opacity = thread > 0 && thread < 1 ? 0.9 : 0;
  priyaPool.material.opacity = members * 0.25 + (thread >= 1 ? 0.15 * pulse : 0);
  const wp = routeCurve.getPointAt(clamp(go, 0, 1));
  walker.position.copy(wp).setY(0.55); walkerHalo.position.copy(wp).setY(0.5);
  const wa = go > 0 && go < 1 ? 1 : 0;
  walker.material.opacity = 0.95 * wa; walkerHalo.material.opacity = 0.55 * wa;
  // the chip leaving through the roof
  if (chip >= 0) {
    const a = V(2.85, CT + 0.25, -2.86), b = V(2.4, 4.6, -1.6), c = V(3.0, 7.0, -0.6);
    const u = io3(clamp(chip)), p = new THREE.Vector3().copy(a).multiplyScalar((1 - u) ** 2).add(b.clone().multiplyScalar(2 * (1 - u) * u)).add(c.clone().multiplyScalar(u * u));
    chipGlow.position.copy(p); chipGlow.material.opacity = chip > 0 && chip < 1 ? 0.8 : 0;
    A.chip = proj(local(p));
  } else chipGlow.material.opacity = 0;
  // anchors for the HTML layer
  marg.updateMatrixWorld(true);
  A.plug = proj(local(V(0.48, CT + 0.15, -3.2)));
  A.hub = proj(local(V(2.85, CT, -2.86)));
  A.kettle = proj(local(KET.position.clone().add(V(0, 0.12, 0))));
  A.spout = proj(local(KET.position.clone().add(KET.userData.spoutTip)));
  A.lid = proj(local(KET.position.clone().add(V(0, 0.26, 0))));
  A.pxPerM = Math.abs(proj(local(KET.position.clone().add(V(0.1, 0.1, 0))))[0] - proj(local(KET.position.clone().add(V(0, 0.1, 0))))[0]) * 10;
  A.roof = proj(V(marg.position.x, marg.userData.h + marg.userData.rise + 0.6, marg.position.z));
  A.margaret = proj(V(MARG_X, marg.userData.h + marg.userData.rise + 1.0, marg.position.z));
  A.priya = proj(V(priya.position.x, priya.userData.h + priya.userData.rise + 1.2, priya.position.z));
  A.tom = proj(V(tom.position.x, tom.userData.h + tom.userData.rise + 1.2, tom.position.z));
  A.members = members; A.alarm = alarm; A.thread = thread; A.cut = cut;
  return A;
}
function draw() {
  if (!active) return;
  composer.render();
}

// ------------------------------------------------------------------ boot
(async () => {
  await Promise.all([loadTex("ask", "assets/hub-imfine-ring.webp"), loadTex("morning", "assets/hub-morning.webp")]);
  hubScreenMat.map = tex.ask;
  buildPaths();
  scene.updateMatrixWorld(true);
  window.WORLD = { setup, draw };
  window.dispatchEvent(new Event("world-ready"));
})();
