// UEIC 3-D Lab (Phase 2). Every number shown comes from the local API: the physics module
// (analytical calculation), stored simulation runs (simulator output), or the parameter
// registry. Geometry is conceptual unless stated otherwise.
import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from './vendor/three/CSS2DRenderer.js';

/* ------------------------------------------------------------------ helpers */
const $ = (s, el = document) => el.querySelector(s);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fin = v => v !== null && v !== undefined && Number.isFinite(+v);
const fmt = (v, d = 1) => fin(v) ? (+v).toFixed(d) : '–';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(`${r.status}: ${m}`); }
  return r.json();
}
function el(tag, attrs = {}, html) { const e = document.createElement(tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (html !== undefined) e.innerHTML = html; return e; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
const TEMP_STOPS = ['#fdf0dc', '#f9c98e', '#f29a52', '#e0692a', '#b84616', '#7d2b0c'];  // one hue family, light -> dark
const T_LO = 15, T_HI = 95;
function rampColor(stops, x) { x = Math.min(1, Math.max(0, x)); const n = stops.length - 1, i = Math.min(n - 1, Math.floor(x * n));
  return new THREE.Color(stops[i]).lerp(new THREE.Color(stops[i + 1]), x * n - i); }
const tempColor = T => rampColor(TEMP_STOPS, (T - T_LO) / (T_HI - T_LO));
const POWER_STOPS = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];
const powerColor = x => rampColor(POWER_STOPS, x);
function rampCss(stops) { return `linear-gradient(90deg, ${stops.join(',')})`; }
function std(color, extra = {}) { return new THREE.MeshStandardMaterial({color, roughness: .55, metalness: .1, ...extra}); }
function box(w, h, d, mat) { return new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); }
function label(text, cls = '') { const d = el('div', {class: 'label3d ' + cls}); d.textContent = text; return new CSS2DObject(d); }
function info(mesh, data) { mesh.userData.info = data; return mesh; }
function tube(points, radius, mat) { return new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p))), 64, radius, 12, false), mat); }
function kv(rows) { return `<div class="kv">${rows.map(([k, v]) => `<span>${esc(k)}</span><span>${v}</span>`).join('')}</div>`; }

/* ------------------------------------------------------------- renderer */
const vp = $('#viewport');
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
vp.appendChild(renderer.domElement);
const labels = new CSS2DRenderer();
Object.assign(labels.domElement.style, {position: 'absolute', top: '0', left: '0', pointerEvents: 'none'});
vp.appendChild(labels.domElement);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
function resize() { const w = vp.clientWidth, h = vp.clientHeight; renderer.setSize(w, h); labels.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix(); }
new ResizeObserver(resize).observe(vp);

function baseScene() {
  const s = new THREE.Scene();
  s.background = new THREE.Color(css('--scene'));
  s.add(new THREE.HemisphereLight(0xffffff, 0x445555, 1.4));
  const d = new THREE.DirectionalLight(0xffffff, 1.6); d.position.set(80, 140, 60); s.add(d);
  return s;
}

/* --------------------------------------------------------- picking */
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
let downAt = null, picked = null;
renderer.domElement.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', e => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4 || !active3d) return;
  const r = renderer.domElement.getBoundingClientRect();
  ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const hit = ray.intersectObjects(active3d.scene.children, true).find(h => { let o = h.object; while (o && !o.userData.info) o = o.parent; return o; });
  let o = hit ? hit.object : null; while (o && !o.userData.info) o = o.parent;
  if (picked && picked.material && picked.material.emissive) picked.material.emissive.setHex(0x000000);
  picked = o;
  if (o && o.material && o.material.emissive) o.material.emissive.setHex(0x333333);
  showInspector(o ? o.userData.info : null);
});
function showInspector(i) {
  const box = $('#inspector');
  if (!i) { box.innerHTML = '<h3>Inspector</h3><p class="muted">Click a component in the scene.</p>'; return; }
  const data = typeof i === 'function' ? i() : i;
  box.innerHTML = `<h3>${esc(data.name)}</h3>${data.role ? `<p>${esc(data.role)}</p>` : ''}${data.values ? kv(data.values) : ''}`
    + (data.params ? `<p class="note">Model parameters: ${data.params.map(p => `<code>${esc(p)}</code>`).join(', ')}</p>` : '')
    + (data.provenance ? `<p class="note">${esc(data.provenance)}</p>` : '');
  box.dataset.live = typeof i === 'function' ? '1' : '';
  box._live = typeof i === 'function' ? i : null;
}
function refreshInspector() { const b = $('#inspector'); if (b._live) showInspector(b._live); }

/* ============================================================ COOLING SCENE */
const cooling = (() => {
  const S = {params: {clock: 1.0, t_sup: 25, flow: 1.0, t_amb: 20, r_cond: 0.035, r_conv_ref: 0.015, kappa_leak: 0.02}, data: null, explode: 0};
  const scene = baseScene();
  const g = new THREE.Group(); scene.add(g);
  const M = {
    sub: std('#3d5a4f'), die: std('#888888'), tim: std('#b9bcbc'), base: std('#b87333', {metalness: .6, roughness: .35}),
    fin: std('#c98a55', {metalness: .6, roughness: .35}), fluid: std('#5aa9e6', {transparent: true, opacity: .55}),
    cover: std('#9fb5c0', {transparent: true, opacity: .14}), pin: std('#5aa9e6'), pout: std('#5aa9e6'),
    hot: std('#e06a2a'), cold: std('#5aa9e6'), pump: std('#6b7b80'), hx: std('#8a979b'),
  };
  const layers = {};
  layers.sub = info(box(70, 2, 70, M.sub), () => ({name: 'Package substrate', role: 'Mechanical carrier and power/signal fan-out. Not part of the thermal path in the lumped model.', provenance: 'Conceptual geometry.'}));
  layers.die = info(box(30, 1, 30, M.die), () => part('Compute die (junction)', 'Where the heat is generated. Its temperature drives leakage power.', 'junction', ['p_dyn_max', 'p_leak_ref', 'kappa_leak', 'v_min_ratio']));
  layers.tim = info(box(32, .4, 32, M.tim), () => part('Thermal interface + lid', 'Conduction path die → cold plate. Lumped into R_cond with the die and lid.', null, ['r_cond'], [['R_cond', resK('conduction')]]));
  layers.base = info(box(60, 4, 60, M.base), () => part('Cold-plate base (wetted wall)', 'Spreads heat into the fins. Its wetted surface temperature is the wall node.', 'wall', ['r_conv_ref', 'n_conv'], [['R_conv', resK('convection')]]));
  layers.fins = new THREE.Group(); layers.fluid = new THREE.Group();
  const NF = 15, span = 46;
  for (let i = 0; i < NF; i++) {
    const z = -span / 2 + i * span / (NF - 1);
    layers.fins.add(info(box(46, 3, .9, M.fin), () => part('Microchannel fins', 'Increase wetted area. Convective resistance falls with flow as flow^-n_conv.', 'wall', ['r_conv_ref', 'n_conv'])));
    if (i < NF - 1) { const f = box(46, 2.6, span / (NF - 1) - 1.0, M.fluid); f.position.z = z + span / (NF - 1) / 2; layers.fluid.add(info(f, () => part('Coolant in channels', 'Water warms as it crosses the plate; mean coolant temperature sets the convective driving difference.', 'coolant_mean', ['flow_design_lpm', 'water_cp'], [['R_caloric', resK('caloric')]]))); }
    layers.fins.children[i].position.z = z;
  }
  layers.cover = info(box(60, 1.5, 60, M.cover), () => ({name: 'Cold-plate cover', role: 'Closes the channels. Shown translucent.', provenance: 'Conceptual geometry.'}));
  const base = {sub: 0, die: 1.5, tim: 2.2, base: 4.4, fins: 7.9, fluid: 7.9, cover: 10.15};
  const lift = {sub: 0, die: 6, tim: 12, base: 20, fins: 26, fluid: 26, cover: 36};
  for (const k in layers) g.add(layers[k]);
  const pin = info(tube([[-75, 7, 0], [-55, 7, 0], [-30, 7.9, 0]], 3, M.pin), () => part('Supply pipe (coolant in)', 'Water from the plant at the supply setpoint.', 'coolant_in', ['t_sup_min', 't_sup_max']));
  const pout = info(tube([[30, 7.9, 0], [55, 7, 0], [75, 7, 0]], 3, M.pout), () => part('Return pipe (coolant out)', 'Node return temperature (all 8 accelerators in parallel).', 'coolant_out', ['flow_design_lpm']));
  const loop = tube([[75, 7, 0], [95, 7, 0], [100, 7, 40], [60, 7, 70], [-60, 7, 70], [-100, 7, 40], [-95, 7, 0], [-75, 7, 0]], 2.4, M.cold);
  const pump = info(new THREE.Mesh(new THREE.CylinderGeometry(9, 9, 14, 24), M.pump), () => part('Pump', 'Moves coolant. Power ∝ pressure drop × volume flow; pressure drop ∝ flow^m.', null, ['dp_ref', 'm_dp', 'eta_pump'], [['Pump power', S.data && S.data.power_W ? fmt(S.data.power_W.pump, 0) + ' W' : '–']]));
  pump.position.set(-60, 7, 70);
  const hx = info(box(36, 18, 20, M.hx), () => part('Heat rejection (dry cooler + trim chiller)', 'Dry cooler cools toward ambient + approach; the chiller trims the rest. Fans run on all rejected heat.', null, ['dt_drycooler', 'eta_ii_chiller', 'fan_ratio'],
    [['Free cooling', S.data && S.data.heat_W ? fmt(S.data.heat_W.free_cooling / 1000, 2) + ' kW' : '–'], ['Chiller work', S.data && S.data.power_W ? fmt(S.data.power_W.chiller, 0) + ' W' : '–'], ['Fans', S.data && S.data.power_W ? fmt(S.data.power_W.fans, 0) + ' W' : '–']]));
  hx.position.set(60, 9, 70);
  scene.add(pin, pout, loop, pump, hx);
  const L = {j: label(''), w: label(''), i: label(''), o: label(''), p: label('Pump'), h: label('Plant')};
  L.j.position.set(0, 3, 0); layers.die.add(L.j); L.w.position.set(28, 3, 28); layers.base.add(L.w);
  L.i.position.set(-75, 13, 0); L.o.position.set(75, 13, 0); L.p.position.set(-60, 20, 70); L.h.position.set(60, 22, 70);
  scene.add(L.i, L.o, L.p, L.h);
  const grid = new THREE.GridHelper(260, 26, css('--grid'), css('--grid')); grid.position.y = -2; scene.add(grid);
  // flow particles: schematic, speed proportional to the flow factor
  const NP = 140, pg = new THREE.BufferGeometry(), pp = new Float32Array(NP * 3);
  for (let i = 0; i < NP; i++) { pp[3 * i] = -23 + Math.random() * 46; pp[3 * i + 1] = 7.9; pp[3 * i + 2] = -span / 2 + (Math.floor(Math.random() * (NF - 1)) + .5) * span / (NF - 1); }
  pg.setAttribute('position', new THREE.BufferAttribute(pp, 3));
  const particles = new THREE.Points(pg, new THREE.PointsMaterial({color: 0xffffff, size: 1.1})); g.add(particles);

  function resK(k) { return S.data ? fmt(S.data.resistances_K_per_W[k] * 1000, 1) + ' mK/W' : '–'; }
  function part(name, role, node, params, extra = []) {
    const d = S.data, vals = [];
    if (node && d && d.temperatures_C) vals.push(['Temperature', fmt(d.temperatures_C[node], 1) + ' °C']);
    return {name, role, values: vals.concat(extra), params, provenance: 'Geometry conceptual. Values: analytical calculation from the UEIC physics module (steady state, all 8 accelerators busy); inputs mostly class E/F.'};
  }
  function applyExplode() { for (const k in layers) layers[k].position.y = base[k] + S.explode * lift[k]; particles.position.y = S.explode * lift.fluid; }
  function paint() {
    const d = S.data; if (!d || !d.temperatures_C) {
      L.j.element.textContent = 'thermal runaway: no steady state'; M.die.color.set('#d03b3b'); return; }
    const T = d.temperatures_C;
    M.die.color.copy(tempColor(T.junction)); M.base.color.copy(tempColor(T.wall)); M.fin.color.copy(tempColor(T.wall));
    M.fluid.color.copy(tempColor(T.coolant_mean)); M.pin.color.copy(tempColor(T.coolant_in)); M.pout.color.copy(tempColor(T.coolant_out));
    M.cold.color.copy(tempColor(T.coolant_in));
    L.j.element.textContent = `junction ${fmt(T.junction, 1)} °C`; L.w.element.textContent = `wall ${fmt(T.wall, 1)} °C`;
    L.i.element.textContent = `in ${fmt(T.coolant_in, 1)} °C`; L.o.element.textContent = `out ${fmt(T.coolant_out, 1)} °C`;
    L.p.element.textContent = `pump ${fmt(d.power_W.pump, 0)} W`; L.h.element.textContent = `fans ${fmt(d.power_W.fans, 0)} W · chiller ${fmt(d.power_W.chiller, 0)} W`;
  }
  const fetchData = debounce(async () => {
    const q = new URLSearchParams(Object.entries(S.params).map(([k, v]) => [k, String(v)]));
    try { S.data = await api('/api/physics/coldplate?' + q); paint(); readout(); refreshInspector(); }
    catch (e) { $('#cool-readout').innerHTML = `<p class="note">Could not compute: ${esc(e.message)}</p>`; }
  }, 120);
  function slider(id, lab, min, max, step, key, f, note) {
    return `<div class="ctl"><label for="${id}">${lab}</label><output id="${id}-o"></output><input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${S.params[key]}" data-key="${key}" data-f="${f}">${note ? `<small>${note}</small>` : ''}</div>`;
  }
  function readout() {
    const d = S.data, box = $('#cool-readout'); if (!box) return;
    if (!d || !d.temperatures_C) { box.innerHTML = '<p><span class="pill crit">thermal runaway</span> Leakage grows faster than the plate can remove heat at this setting.</p>'; return; }
    const P = d.power_W, T = d.temperatures_C, R = d.resistances_K_per_W, tot = R.total;
    const seg = [['caloric', R.caloric, 'var(--s3)'], ['convection', R.convection, 'var(--s1)'], ['conduction', R.conduction, 'var(--s2)']];
    let x = 0; const bars = seg.map(([k, v, c]) => { const w = 100 * v / tot, s = `<rect x="${x}%" y="0" width="${Math.max(w - .5, .5)}%" height="14" rx="2" style="fill:${c}"></rect>`; x += w; return s; }).join('');
    box.innerHTML = `<span class="pill ${d.within_target ? 'good' : 'crit'}">${d.within_target ? 'within' : 'above'} ${d.limits_C.target} °C target</span>`
      + kv([['Junction', fmt(T.junction, 1) + ' °C'], ['Coolant out', fmt(T.coolant_out, 1) + ' °C'], ['Power per accelerator', fmt(P.chip, 0) + ' W'], ['of which leakage', fmt(P.chip_leakage, 0) + ' W'],
        ['Pump', fmt(P.pump, 0) + ' W'], ['Fans', fmt(P.fans, 0) + ' W'], ['Chiller', fmt(P.chiller, 0) + ' W'], ['Node grid power', fmt(P.grid / 1000, 2) + ' kW'], ['Energy per work-second', fmt(d.energy_per_work_J, 1) + ' J']])
      + `<div><svg width="100%" height="14" role="img" aria-label="thermal resistance stack">${bars}</svg><p class="note">Resistance stack, ${fmt(tot * 1000, 1)} mK/W in total: caloric (coolant warming) · convection · conduction + TIM.</p></div>`;
  }
  function panel() {
    const c = $('#controls');
    c.innerHTML = `<h3>Cooling system</h3><p class="note">Change an input; temperatures and powers are recomputed by <code>GET /api/physics/coldplate</code> using the same functions as the simulator.</p>`
      + slider('c-clock', 'Clock (fraction of max)', .5, 1, .05, 'clock', 2) + slider('c-tsup', 'Supply temperature', 12, 45, 1, 't_sup', 0, '°C')
      + slider('c-flow', 'Flow (× design)', .5, 2, .05, 'flow', 2, '1× = 1.2 L/min per accelerator') + slider('c-amb', 'Ambient', 0, 40, 1, 't_amb', 0, '°C')
      + `<h3>Assumptions (class F/E)</h3>` + slider('c-rcond', 'R conduction (K/W)', .02, .06, .001, 'r_cond', 3)
      + slider('c-rconv', 'R convection at design flow (K/W)', .008, .03, .001, 'r_conv_ref', 3) + slider('c-kappa', 'Leakage–temperature coefficient (1/K)', .005, .04, .001, 'kappa_leak', 3)
      + `<div class="ctl"><label for="c-explode">Exploded view</label><output id="c-explode-o"></output><input type="range" id="c-explode" min="0" max="1" step=".01" value="${S.explode}"></div><div id="cool-readout"></div>`;
    c.querySelectorAll('input[data-key]').forEach(inp => { const o = $('#' + inp.id + '-o'); const show = () => o.textContent = (+inp.value).toFixed(+inp.dataset.f); show();
      inp.addEventListener('input', () => { S.params[inp.dataset.key] = +inp.value; show(); fetchData(); }); });
    const ex = $('#c-explode'); const exo = $('#c-explode-o'); exo.textContent = ex.value;
    ex.addEventListener('input', () => { S.explode = +ex.value; exo.textContent = (+ex.value).toFixed(2); applyExplode(); });
    readout();
  }
  return {
    id: 'cooling', title: 'Cooling system', scene,
    view: {pos: [125, 120, 175], target: [5, 6, 28]},
    badge: '<b>Conceptual geometry.</b> Temperatures and powers: analytical calculation from the lumped physics model (steady state, all 8 accelerators busy). Inputs are mostly class E/F assumptions. Flow-particle speed is schematic.',
    legend: () => `<span>Temperature</span><div class="ramp" style="background:${rampCss(TEMP_STOPS)}"></div><div class="ramp-labels"><span>${T_LO} °C</span><span>${T_HI} °C</span></div>`,
    activate() { panel(); applyExplode(); fetchData(); },
    tick(dt) { const sp = 18 * S.params.flow, a = pg.attributes.position; for (let i = 0; i < NP; i++) { a.array[3 * i] += sp * dt; if (a.array[3 * i] > 23) a.array[3 * i] = -23; } a.needsUpdate = true; },
    get data() { return S.data; },
  };
})();

/* =========================================================== FACILITY SCENE */
const facility = (() => {
  const S = {exp: null, runs: [], run: null, ts: null, cmp: null, cmpTs: null, i: 0, playing: false, speed: 10, overlay: 'temperature', acc: 0};
  const scene = baseScene();
  const grid = new THREE.GridHelper(220, 22, css('--grid'), css('--grid')); scene.add(grid);
  const M = {frame: new THREE.LineBasicMaterial({color: css('--ink2')}), pdu: std('#7d8a8e'), cdu: std('#7d8a8e'), tank: std('#9aa8ad'), pump: std('#5f6d71'),
    sup: std('#5aa9e6'), ret: std('#e06a2a'), dry: std('#8f9ca0'), chil: std('#8f9ca0'), reuse: std('#8f9ca0', {transparent: true, opacity: .35}), fan: std('#3b4548')};
  const chips = [], chipMats = [];
  const rack = new THREE.Group(); scene.add(rack);
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(14, 44, 22)), M.frame); frame.position.y = 22; rack.add(frame);
  for (let i = 0; i < 8; i++) {
    const m = std('#888888'); chipMats.push(m);
    const c = info(box(12, 3.2, 19, m), () => cur(`Accelerator ${i}`, 'One accelerator module on the liquid loop. Its junction temperature is the per-chip 1-minute mean from the run.',
      [[`Tj (accelerator ${i})`, v(`Tj${i}`, 1, '°C')], ['Hottest junction (node)', v('T_max', 1, '°C')]], ['p_dyn_max', 'p_leak_ref', 'kappa_leak', 't_throttle']));
    c.position.set(0, 4 + i * 5, 0); rack.add(c); chips.push(c);
  }
  const rackLabel = label('rack'); rackLabel.position.set(0, 48, 0); rack.add(rackLabel);
  const pdu = info(box(10, 30, 16, M.pdu), () => cur('Power conversion (UPS, PSU, VRs)', 'Grid-to-chip conversion; its losses are heat outside the liquid loop (not modelled further).', [['IT power', v('P_it', 0, 'W', 1)], ['Conversion loss (η model)', convLoss()]], ['eta_conv']));
  pdu.position.set(-30, 15, 0); scene.add(pdu);
  const cdu = info(box(12, 26, 16, M.cdu), () => cur('Coolant distribution unit', 'Houses the pump and the supply tank (the loop thermal mass in dynamic-plant runs).', [['Supply temperature', v('T_sup', 1, '°C')], ['Commanded supply', v('T_sup_cmd', 1, '°C')], ['Flow', v('flow', 2, '× design')]], ['loop_mass_kg', 'tsup_ramp_K_per_min']));
  cdu.position.set(30, 13, 0); scene.add(cdu);
  const tank = info(new THREE.Mesh(new THREE.CylinderGeometry(5, 5, 14, 24), M.tank), () => cur('Supply tank (thermal storage)', 'Well-mixed tank between plant and chips; buffers setpoint changes. Absent (0 kg) in quasi-steady runs.', [['Tank / supply temperature', v('T_sup', 1, '°C')]], ['loop_mass_kg']));
  tank.position.set(30, 33, 0); scene.add(tank);
  const pump = info(new THREE.Mesh(new THREE.CylinderGeometry(4, 4, 8, 20), M.pump), () => cur('Pump', 'Pump power rises steeply with flow.', [['Pump power', v('P_pump', 0, 'W')], ['Flow', v('flow', 2, '× design')]], ['dp_ref', 'm_dp', 'eta_pump']));
  pump.position.set(30, 4, 12); scene.add(pump);
  const sup = info(tube([[24, 8, -6], [12, 8, -6], [6, 8, -6], [6, 40, -6]], 1.6, M.sup), () => cur('Supply line', 'Coolant to the accelerators.', [['Supply temperature', v('T_sup', 1, '°C')]], []));
  const ret = info(tube([[6, 40, 6], [6, 10, 6], [12, 10, 6], [24, 10, 6]], 1.6, M.ret), () => cur('Return line', 'Coolant from the accelerators.', [['Return temperature', v('T_ret', 1, '°C')]], []));
  const out1 = tube([[36, 20, 0], [60, 20, 0], [70, 10, -25]], 1.6, M.ret), out2 = tube([[36, 6, -4], [62, 6, -10], [70, 6, 22]], 1.6, M.sup);
  scene.add(sup, ret, out1, out2);
  const dry = info(box(26, 8, 18, M.dry), () => cur('Dry cooler (free cooling)', 'Cools return water toward ambient + approach; no compressor.', [['Fan power (all heat rejection)', v('P_fan', 0, 'W')]], ['dt_drycooler', 'fan_ratio']));
  dry.position.set(78, 4, -25); scene.add(dry);
  const fans = []; for (let k = 0; k < 3; k++) { const f = new THREE.Mesh(new THREE.CylinderGeometry(3.4, 3.4, .6, 20), M.fan); f.position.set(70 + k * 8, 8.5, -25); scene.add(f); fans.push(f); }
  const chil = info(box(18, 14, 14, M.chil), () => cur('Trim chiller', 'Vapour-compression chiller for what free cooling cannot reach; COP = η_II × Carnot.', [['Chiller power', v('W_ch', 0, 'W')]], ['eta_ii_chiller', 'dt_evap', 'dt_cond']));
  chil.position.set(78, 7, 22); scene.add(chil);
  const reuse = info(box(12, 10, 10, M.reuse), () => ({name: 'Heat-reuse exchanger (not modelled)', role: 'Placeholder for a heat user. UEIC reports reusable heat (return ≥ 45 °C) and its exergy but never nets it against consumption.', provenance: 'Conceptual.'}));
  reuse.position.set(55, 5, 45); scene.add(reuse);
  const Lg = label(''); Lg.position.set(0, 58, 0); scene.add(Lg);
  const Lc = label(''); Lc.position.set(78, 18, 22); scene.add(Lc);
  const Ld = label(''); Ld.position.set(78, 14, -25); scene.add(Ld);
  const Lt = label(''); Lt.position.set(30, 45, 0); scene.add(Lt);

  const has = k => S.ts && S.ts[k];
  function at(ts, k) { return ts && ts[k] ? ts[k][Math.min(S.i, ts[k].length - 1)] : null; }
  function v(k, d, unit, scale = 1) { const a = at(S.ts, k), b = at(S.cmpTs, k);
    const s = x => fin(x) ? `${fmt(x * scale, d)} ${unit}` : '–';
    return S.cmpTs && fin(b) ? `${s(a)} <span class="muted">vs ${s(b)}</span>` : s(a); }
  function convLoss() { const p = at(S.ts, 'P_it'); return fin(p) ? fmt(p * (1 / 0.94 - 1), 0) + ' W' : '–'; }
  function cur(name, role, values, params) { return {name, role, values, params, provenance: S.run ? `Simulator output, 1-minute averages. Run ${S.run.run_id.slice(0, 8)} (${S.run.scenario} · ${S.run.policy} · ${S.run.variant} · seed ${S.run.seed})${S.cmp ? `; compared with ${S.cmp.policy} · ${S.cmp.variant}` : ''}. Geometry conceptual.` : 'Load a run.'}; }
  function paint() {
    if (!S.ts) return;
    const t = at(S.ts, 't');
    const Tmean = at(S.ts, 'T_mean');
    for (let i = 0; i < 8; i++) {
      const Tj = has(`Tj${i}`) ? at(S.ts, `Tj${i}`) : Tmean;
      if (S.overlay === 'temperature') chipMats[i].color.copy(tempColor(Tj));
      else chipMats[i].color.copy(powerColor((at(S.ts, 'P_it') || 0) / 8 / 750));
    }
    if (S.overlay === 'temperature') { M.sup.color.copy(tempColor(at(S.ts, 'T_sup'))); M.ret.color.copy(tempColor(at(S.ts, 'T_ret'))); M.tank.color.copy(tempColor(at(S.ts, 'T_sup')));
      M.chil.color.set('#8f9ca0'); M.dry.color.set('#8f9ca0'); M.pdu.color.set('#7d8a8e'); M.pump.color.set('#5f6d71'); }
    else { const pg = at(S.ts, 'P_grid') || 1; M.chil.color.copy(powerColor((at(S.ts, 'W_ch') || 0) / pg * 5)); M.dry.color.copy(powerColor((at(S.ts, 'P_fan') || 0) / pg * 20));
      M.pdu.color.copy(powerColor(0.06 / 0.2)); M.pump.color.copy(powerColor((at(S.ts, 'P_pump') || 0) / pg * 20)); M.sup.color.set('#8f9ca0'); M.ret.color.set('#8f9ca0'); M.tank.color.set('#9aa8ad'); }
    Lg.element.textContent = `grid ${fmt(at(S.ts, 'P_grid') / 1000, 2)} kW · t = ${fmt(t / 3600, 2)} h`;
    Lc.element.textContent = `chiller ${fmt(at(S.ts, 'W_ch'), 0)} W`; Ld.element.textContent = `fans ${fmt(at(S.ts, 'P_fan'), 0)} W`;
    Lt.element.textContent = `supply ${fmt(at(S.ts, 'T_sup'), 1)} °C`;
    const sl = $('#f-time'); if (sl) { sl.value = S.i; $('#f-time-o').textContent = `${fmt(t / 3600, 2)} h`; }
    drawSpark(); refreshInspector();
  }
  function drawSpark() {
    const host = $('#f-spark'); if (!host || !S.ts) return;
    const W = host.clientWidth || 300, H = 70, xs = S.ts.t, n = xs.length;
    const series = [[S.ts.P_grid, 'var(--s5)']].concat(S.cmpTs ? [[S.cmpTs.P_grid, 'var(--s4)']] : []);
    const all = series.flatMap(s => s[0]).filter(fin), lo = Math.min(...all), hi = Math.max(...all);
    const X = i => i / Math.max(n - 1, 1) * (W - 4) + 2, Y = v => H - 4 - (v - lo) / ((hi - lo) || 1) * (H - 8);
    host.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="grid power over the run">${series.map(([s, c]) => `<polyline fill="none" stroke-width="1.6" style="stroke:${c}" points="${s.map((v, i) => `${X(i)},${Y(v)}`).join(' ')}"/>`).join('')}<line x1="${X(S.i)}" x2="${X(S.i)}" y1="0" y2="${H}" style="stroke:var(--ink2)"/></svg>`
      + `<p class="note">Grid power over the run: <span style="color:var(--s5)">■</span> selected${S.cmpTs ? ' · <span style="color:var(--s4)">■</span> comparison' : ''} (${fmt(lo / 1000, 1)}–${fmt(hi / 1000, 1)} kW)</p>`;
  }
  async function loadExperiments() {
    const ex = (await api('/api/experiments')).filter(x => x.status === 'completed' && !x.measurement);
    const latest = {}; ex.forEach(x => { latest[x.key] = x; });
    return Object.values(latest).sort((a, b) => a.key.localeCompare(b.key));
  }
  async function selectExperiment(id) {
    S.exp = id; S.runs = (await api(`/api/experiments/${id}/runs?metrics=E_grid_kWh`)).filter(r => r.status === 'completed' && r.timeseries_path);
    const sel = $('#f-run'), cs = $('#f-cmp');
    const lab = r => `${r.scenario} · ${r.policy} · ${r.variant} · seed ${r.seed}`;
    sel.innerHTML = S.runs.map((r, i) => `<option value="${i}">${esc(lab(r))}</option>`).join('');
    cs.innerHTML = '<option value="">none</option>' + S.runs.map((r, i) => `<option value="${i}">${esc(lab(r))}</option>`).join('');
    const pref = S.runs.findIndex(r => r.scenario === 'S3_hot' && r.policy === 'joint' && r.variant !== 'quasi_steady');
    sel.value = pref >= 0 ? pref : 0; await selectRun(+sel.value);
    const pc = S.runs.findIndex(r => S.run && r.scenario === S.run.scenario && r.variant === S.run.variant && r.policy === 'independent');
    if (pc >= 0) { cs.value = pc; await selectCmp(pc); }
  }
  async function selectRun(i) { S.run = S.runs[i]; if (!S.run) return; S.ts = await api(`/api/runs/${S.run.run_id}/timeseries`); S.i = Math.min(S.i, S.ts.t.length - 1);
    const sl = $('#f-time'); sl.max = S.ts.t.length - 1; badge(); paint(); }
  async function selectCmp(i) { S.cmp = i === '' ? null : S.runs[i]; S.cmpTs = S.cmp ? await api(`/api/runs/${S.cmp.run_id}/timeseries`) : null; paint(); }
  function badge() { $('#badge').innerHTML = S.run ? `<b>Simulated run</b> ${esc(S.exp)} · ${esc(S.run.scenario)} · ${esc(S.run.policy)} · ${esc(S.run.variant)} · seed ${S.run.seed}. Values are simulator outputs (1-minute averages; class E/F inputs). Geometry conceptual.` : 'Loading…'; }
  async function panel() {
    const c = $('#controls');
    c.innerHTML = `<h3>Facility playback</h3><label class="muted" for="f-exp">Experiment</label><select id="f-exp"></select>
      <label class="muted" for="f-run">Run (runs with stored time series)</label><select id="f-run"></select>
      <label class="muted" for="f-cmp">Compare with (before / after)</label><select id="f-cmp"></select>
      <div class="ctl"><label for="f-time">Time</label><output id="f-time-o"></output><input type="range" id="f-time" min="0" max="1" step="1" value="0"></div>
      <div class="row"><button class="btn primary" id="f-play" type="button">Play</button><label class="muted" for="f-speed">speed</label>
      <select id="f-speed" style="width:auto"><option value="5">5 min/s</option><option value="10" selected>10 min/s</option><option value="30">30 min/s</option></select>
      <button class="btn" id="f-reset" type="button">Reset to start</button></div>
      <div class="row" role="radiogroup" aria-label="Overlay"><label><input type="radio" name="ov" value="temperature" checked> Temperature</label><label><input type="radio" name="ov" value="power"> Power</label></div>
      <div id="f-spark"></div>`;
    const exps = await loadExperiments(); const es = $('#f-exp');
    es.innerHTML = exps.map(x => `<option value="${x.id}">${esc(x.key)} · ${esc(x.title.slice(0, 48))}</option>`).join('');
    const def = exps.find(x => x.key === 'E006') || exps.find(x => x.key === 'E001') || exps[0];
    es.value = def.id;
    es.addEventListener('change', () => selectExperiment(es.value));
    $('#f-run').addEventListener('change', e => selectRun(+e.target.value));
    $('#f-cmp').addEventListener('change', e => selectCmp(e.target.value));
    $('#f-time').addEventListener('input', e => { S.i = +e.target.value; paint(); });
    $('#f-play').addEventListener('click', () => { S.playing = !S.playing; $('#f-play').textContent = S.playing ? 'Pause' : 'Play'; });
    $('#f-speed').addEventListener('change', e => { S.speed = +e.target.value; });
    $('#f-reset').addEventListener('click', () => { S.i = 0; paint(); });
    c.querySelectorAll('input[name=ov]').forEach(r => r.addEventListener('change', () => { S.overlay = r.value; legendUpdate(); paint(); }));
    await selectExperiment(def.id);
  }
  function legendUpdate() { $('#legend3d').innerHTML = S.overlay === 'temperature'
    ? `<span>Temperature</span><div class="ramp" style="background:${rampCss(TEMP_STOPS)}"></div><div class="ramp-labels"><span>${T_LO} °C</span><span>${T_HI} °C</span></div>`
    : `<span>Power share (relative)</span><div class="ramp" style="background:${rampCss(POWER_STOPS)}"></div><div class="ramp-labels"><span>low</span><span>high</span></div>`; }
  return {
    id: 'facility', title: 'Facility', scene, view: {pos: [-60, 90, 150], target: [25, 15, 0]},
    badge: 'Loading…', legend: () => '',
    activate() { panel().catch(e => { $('#controls').innerHTML = `<p class="note">${esc(e.message)}</p>`; }); legendUpdate(); },
    tick(dt) { fans.forEach(f => f.rotation.y += dt * (1 + 8 * ((at(S.ts, 'P_fan') || 0) / 300)));
      if (S.playing && S.ts) { S.acc += dt * S.speed; if (S.acc >= 1) { S.i = (S.i + Math.floor(S.acc)) % S.ts.t.length; S.acc %= 1; paint(); } } },
  };
})();

/* =============================================================== CHIP SCENE */
const chip = (() => {
  const S = {explode: .35, candidate: false, colorByT: false};
  const scene = baseScene();
  const g = new THREE.Group(); scene.add(g);
  const DIM = {substrate: [62, 1.6, 62], interposer: [46, .6, 38], die: [26, .8, 30], hbm: [8, 4, 10], lid: [52, 1.2, 52], tim: [30, .3, 32], plate: [60, 4, 60]};
  const mk = (k, c, o = {}) => box(...DIM[k], std(c, o));
  const P = 'Dimensions are hypothetical (mm, illustrative). Not a manufacturable design.';
  const parts = {
    substrate: info(mk('substrate', '#3d5a4f'), {name: 'Package substrate', role: 'Routes power and I/O to the board. Hosts voltage regulators near the die in some designs.', params: ['eta_conv'], provenance: P}),
    interposer: info(mk('interposer', '#56656a'), {name: 'Silicon interposer', role: 'Wide, short wires between the compute die and HBM. Off-chip data movement costs far more energy than arithmetic (L14/L15).', params: ['beta_memory'], provenance: P}),
    die: info(mk('die', '#7d8a8e'), {name: 'Compute die', role: 'Matrix engines, caches and control. Dynamic power ∝ activity × frequency × V²; leakage rises with temperature.', params: ['p_dyn_max', 'v_min_ratio', 'p_leak_ref', 'kappa_leak'], provenance: P}),
    tim: info(mk('tim', '#b9bcbc'), {name: 'Thermal interface material', role: 'First resistance between die and lid; part of R_cond.', params: ['r_cond'], provenance: P}),
    lid: info(mk('lid', '#9aa3a6', {transparent: true, opacity: .35}), {name: 'Lid / heat spreader', role: 'Spreads heat to the cold plate; part of R_cond.', params: ['r_cond'], provenance: P}),
    plate: info(mk('plate', '#b87333', {transparent: true, opacity: .3, metalness: .6}), {name: 'Cold plate', role: 'Convective path to the coolant (see Cooling system tab).', params: ['r_conv_ref', 'n_conv'], provenance: P}),
  };
  const y0 = {substrate: 0, interposer: 1.1, die: 1.8, tim: 2.4, lid: 3.2, plate: 6};
  const lift = {substrate: 0, interposer: 6, die: 12, tim: 20, lid: 28, plate: 38};
  for (const k in parts) g.add(parts[k]);
  const tiles = new THREE.Group(); parts.die.add(tiles);
  const tileMat = std('#2a78d6');
  for (let i = 0; i < 6; i++) for (let j = 0; j < 7; j++) tiles.add(info(box(3, .25, 3, tileMat), {name: 'Compute unit (matrix engine tile)', role: 'Arithmetic for matrix products. Compute-bound work scales with clock (beta ≈ 1).', params: ['beta_compute', 'p_dyn_max'], provenance: P}));
  tiles.children.forEach((t, k) => { const i = Math.floor(k / 7), j = k % 7; t.position.set(-9.5 + j * 3.2, .5, -10 + i * 3.6); });
  const ctrl = info(box(22, .3, 3, std('#eda100')), {name: 'Control logic and schedulers', role: 'Instruction issue, DMA, synchronisation. Small area, steady power.', provenance: P}); ctrl.position.set(0, .5, 12.5); parts.die.add(ctrl);
  const noc = new THREE.Group(); for (let i = 0; i < 6; i++) { const l = box(22, .08, .25, std('#d0d4d3')); l.position.set(0, .4, -8.2 + i * 3.6); noc.add(l); }
  parts.die.add(info(noc, {name: 'On-chip interconnect', role: 'Moves operands between tiles, caches and memory controllers. Its energy is part of data movement.', provenance: P}));
  const sensors = []; [[-11, -13], [11, -13], [-11, 9], [11, 9], [0, -2]].forEach(([x, z]) => { const s = info(new THREE.Mesh(new THREE.SphereGeometry(.7, 16, 12), std('#d03b3b')), {name: 'Thermal sensor', role: 'Feeds the independent hardware protection (throttle at 85 °C) that no controller can override.', params: ['t_throttle', 'throttle_hyst'], provenance: P}); s.position.set(x, .7, z); parts.die.add(s); sensors.push(s); });
  const hbm = new THREE.Group(); parts.interposer.add(hbm);
  [[-18, -10], [-18, 0], [-18, 10], [18, -10], [18, 0], [18, 10]].forEach(([x, z]) => { const st = new THREE.Group();
    for (let k = 0; k < 4; k++) { const l = box(7, .9, 9, std(k % 2 ? '#1baf7a' : '#199e70')); l.position.y = .8 + k * 1.0; st.add(l); }
    st.position.set(x, 0, z); hbm.add(info(st, {name: 'HBM stack', role: 'High-bandwidth DRAM. Memory-bound work (e.g. LLM decode) is limited here, not by clock speed (L09).', params: ['beta_memory', 'activity_memory'], provenance: P})); });
  const vrm = new THREE.Group(); parts.substrate.add(vrm);
  [[-27, 0], [27, 0], [0, -27], [0, 27]].forEach(([x, z]) => { const b = box(x ? 5 : 30, 1.2, z ? 5 : 30, std('#6250d6')); b.position.set(x, 1.2, z); vrm.add(info(b, {name: 'Power-delivery region (voltage regulators)', role: 'Final conversion stage; its losses are part of grid-to-chip conversion efficiency.', params: ['eta_conv'], provenance: P})); });
  const cand = info(box(9, .35, 6.5, std('#e87ba4', {emissive: 0x220011})), {name: 'Candidate: SRAM-heavy decode engine (conceptual)', role: 'Architecture A in docs/08: keep KV-cache and weights close to compute to cut DRAM traffic. Not justified by current evidence; shown to make the trade-off concrete.', provenance: 'Conceptual candidate only. ' + P});
  cand.position.set(6.5, .55, 8.6); cand.visible = false; parts.die.add(cand);
  const Ls = {}; Object.entries({die: 'compute die', interposer: 'interposer + HBM', substrate: 'substrate + VRs', tim: 'TIM', lid: 'lid', plate: 'cold plate'}).forEach(([k, t]) => { const l = label(t); l.position.set(DIM[k][0] / 2 + 6, 0, 0); parts[k].add(l); Ls[k] = l; });
  const grid = new THREE.GridHelper(200, 20, css('--grid'), css('--grid')); grid.position.y = -1; scene.add(grid);
  function apply() { for (const k in parts) parts[k].position.y = y0[k] + S.explode * lift[k]; cand.visible = S.candidate;
    const d = cooling.data; const Tj = d && d.temperatures_C ? d.temperatures_C.junction : null;
    parts.die.material.color.set(S.colorByT && fin(Tj) ? tempColor(Tj) : new THREE.Color('#7d8a8e')); }
  function panel() {
    $('#controls').innerHTML = `<h3>Accelerator chip (conceptual)</h3><p class="note">Layers and blocks of a generic AI accelerator package, linked to the model parameters they correspond to. Click a part.</p>
      <div class="ctl"><label for="k-ex">Exploded view</label><output id="k-ex-o"></output><input type="range" id="k-ex" min="0" max="1" step=".01" value="${S.explode}"></div>
      <label><input type="checkbox" id="k-cand" ${S.candidate ? 'checked' : ''}> Show candidate decode engine (docs/08, architecture A)</label>
      <label><input type="checkbox" id="k-t" ${S.colorByT ? 'checked' : ''}> Colour die by the junction temperature from the Cooling tab</label>
      <p class="note">The lumped model has one junction node per chip, so the die is coloured uniformly; it does not resolve hot spots (Phase 5 would need a floorplan-level thermal model).</p>`;
    const ex = $('#k-ex'); const o = $('#k-ex-o'); o.textContent = ex.value;
    ex.addEventListener('input', () => { S.explode = +ex.value; o.textContent = (+ex.value).toFixed(2); apply(); });
    $('#k-cand').addEventListener('change', e => { S.candidate = e.target.checked; apply(); });
    $('#k-t').addEventListener('change', e => { S.colorByT = e.target.checked; apply(); });
    apply();
  }
  return {id: 'chip', title: 'Accelerator chip', scene, view: {pos: [70, 70, 90], target: [0, 15, 0]},
    badge: '<b>Conceptual model.</b> Dimensions hypothetical; not evidence of manufacturability. Blocks are linked to the simulator parameters they stand for.',
    legend: () => `<span><span style="color:var(--s1)">■</span> compute · <span style="color:var(--s3)">■</span> HBM · <span style="color:var(--s5)">■</span> candidate · <span style="color:#6250d6">■</span> power delivery · <span style="color:#d03b3b">●</span> sensors</span>`,
    activate() { panel(); }, tick() {}};
})();

/* ========================================================== PHOTONIC SCENE */
const photonic = (() => {
  const scene = baseScene();
  const g = new THREE.Group(); scene.add(g);
  const Q = 'Qualitative only. Published efficiency gains for photonic matrix engines are largely projections (L35, class E), so no numbers are shown.';
  const board = box(150, 2, 70, std('#3d5a4f')); g.add(board);
  const wg = std('#8fd3ff', {emissive: 0x0b3a55});
  const N = 6, x0 = -40, x1 = 40;
  const laser = info(box(14, 6, 10, std('#d03b3b')), {name: 'Laser source', role: 'Supplies optical power. Energy sink: wall-plug efficiency of the laser, often the single largest overhead.', provenance: Q});
  laser.position.set(-68, 4, 0); g.add(laser);
  const dac = new THREE.Group(), mod = new THREE.Group(), pd = new THREE.Group(), adc = new THREE.Group(); g.add(dac, mod, pd, adc);
  for (let i = 0; i < N; i++) {
    const z = -25 + i * 10;
    const w = box(x1 - x0 + 20, .6, .8, wg); w.position.set((x0 + x1) / 2, 2, z); g.add(info(w, {name: 'Waveguide', role: 'Carries light between stages. Energy sink: propagation and insertion loss, which the laser must make up.', provenance: Q}));
    const d = box(6, 3, 5, std('#6250d6')); d.position.set(-52, 3, z); dac.add(info(d, {name: 'DAC (electronic → analog)', role: 'Converts digital activations to drive voltages. Energy per conversion grows with precision; a key conversion overhead.', provenance: Q}));
    const m = box(5, 2, 3, std('#eda100')); m.position.set(-44, 3, z); mod.add(info(m, {name: 'Modulator', role: 'Encodes values onto light. Energy sink: modulator drive energy per symbol.', provenance: Q}));
    const p = box(4, 2.4, 4, std('#1baf7a')); p.position.set(48, 3, z); pd.add(info(p, {name: 'Photodetector', role: 'Converts light back to current. Its sensitivity sets how much laser power is needed for a given precision.', provenance: Q}));
    const a = box(6, 3, 5, std('#6250d6')); a.position.set(56, 3, z); adc.add(info(a, {name: 'ADC (analog → digital)', role: 'Digitises results. Often dominates the electronic energy of analog/optical accelerators at useful precision.', provenance: Q}));
  }
  const mzis = new THREE.Group(); g.add(mzis);
  for (let c = 0; c < 6; c++) for (let r = 0; r < N - 1; r++) { if ((c + r) % 2) continue;
    const t = new THREE.Mesh(new THREE.TorusGeometry(2.6, .7, 10, 24), std('#e87ba4')); t.rotation.x = Math.PI / 2; t.position.set(-30 + c * 12, 2.4, -20 + r * 10);
    mzis.add(info(t, {name: 'Mach-Zehnder interferometer cell (phase shifters)', role: 'Performs the matrix multiply in the optical domain. Energy sink: thermal phase tuning (heaters) to hold calibration; precision limited by fabrication error and drift.', provenance: Q})); }
  const sram = info(box(16, 6, 30, std('#2a78d6')), {name: 'SRAM / HBM interface', role: 'Weights and activations still live in electronic memory; data movement costs remain (L14/L15).', provenance: Q});
  sram.position.set(66, 4, -10); g.add(sram);
  const ctl = info(box(16, 5, 14, std('#7d8a8e')), {name: 'Electronic controller', role: 'Sequencing, calibration loops and non-linear functions, which stay electronic.', provenance: Q});
  ctl.position.set(66, 3.5, 18); g.add(ctl);
  [['laser', -68, 10, 0], ['DAC + modulators', -48, 8, 32], ['MZI mesh', -6, 8, 32], ['detectors + ADC', 52, 8, 32], ['memory + control', 66, 12, 0]].forEach(([t, x, y, z]) => { const l = label(t); l.position.set(x, y, z); g.add(l); });
  const pulses = []; const pm = new THREE.MeshBasicMaterial({color: 0xffffff});
  for (let i = 0; i < 30; i++) { const s = new THREE.Mesh(new THREE.SphereGeometry(.6, 8, 6), pm); s.position.set(x0 - 10 + Math.random() * 100, 2.6, -25 + (i % N) * 10); g.add(s); pulses.push(s); }
  const grid = new THREE.GridHelper(220, 22, css('--grid'), css('--grid')); grid.position.y = -1.2; scene.add(grid);
  return {id: 'photonic', title: 'Photonic concept', scene, view: {pos: [0, 95, 120], target: [0, 0, 0]},
    badge: '<b>Conceptual hybrid photonic–electronic accelerator.</b> Shows where energy is consumed and where conversion losses occur. No efficiency figures: published gains are mostly projections (L35, class E). Pulse motion is illustrative.',
    legend: () => `<span>Energy sinks: <span style="color:#d03b3b">■</span> laser · <span style="color:#6250d6">■</span> DAC/ADC · <span style="color:#eda100">■</span> modulators · <span style="color:#e87ba4">■</span> phase tuning · <span style="color:var(--s1)">■</span> memory</span>`,
    activate() { $('#controls').innerHTML = `<h3>Photonic / hybrid accelerator</h3><p>Optical matrix multiplication only pays off if the light-side savings beat everything it adds: laser wall-plug losses, DAC and ADC conversions, modulator drive, thermal phase tuning, and the electronic memory traffic that remains.</p><p class="note">Status in UEIC: literature only (docs/02, L35). Not modelled in the simulator, and no number on this page is a UEIC result.</p>`; },
    tick(dt) { pulses.forEach(p => { p.position.x += 40 * dt; if (p.position.x > x1 + 10) p.position.x = x0 - 10; }); }};
})();

/* ===================================================== ENERGY FLOW (2-D page) */
async function energyPage(host) {
  host.innerHTML = `<div class="panel"><h2>Energy flow</h2><p class="note">Where one run's grid energy goes, from the stored energy accounting (simulator output). Heat that leaves at ≥ 45 °C is shown separately as reusable; it is part of the heat rejected, never counted as new energy. Drawn in 2-D because a flow diagram reads more clearly flat than in 3-D.</p>
    <div class="row"><select id="e-exp" style="max-width:420px"></select><select id="e-run" style="max-width:420px"></select></div></div>
    <div class="panel scroll"><div id="e-sankey"></div></div><div class="panel" id="e-table"></div>`;
  const exps = (await api('/api/experiments')).filter(x => x.status === 'completed' && !x.measurement);
  const es = $('#e-exp'); es.innerHTML = exps.map(x => `<option value="${x.id}">${esc(x.key)} v${x.version} · ${esc(x.title.slice(0, 50))}</option>`).join('');
  const def = [...exps].reverse().find(x => x.key === 'E006') || [...exps].reverse().find(x => x.key === 'E001'); if (def) es.value = def.id;
  async function loadRuns() { const runs = (await api(`/api/experiments/${es.value}/runs?metrics=E_grid_kWh`)).filter(r => r.status === 'completed');
    const rs = $('#e-run'); rs.innerHTML = runs.map(r => `<option value="${r.run_id}">${esc(`${r.scenario} · ${r.policy} · ${r.variant} · seed ${r.seed}`)}</option>`).join('');
    const p = runs.find(r => r.scenario === 'S3_hot' && r.policy === 'fixed') || runs[0]; if (p) rs.value = p.run_id; await draw(); }
  async function draw() {
    const f = await api(`/api/runs/${$('#e-run').value}/energyflow`);
    sankey($('#e-sankey'), f.links);
    $('#e-table').innerHTML = `<h3>Accounting</h3>` + kv(f.links.map(l => [`${l.source} → ${l.target}`, fmt(l.kWh, 3) + ' kWh']).concat([
      ['Grid total', fmt(f.grid_kWh, 3) + ' kWh'], ['Grid minus its five uses (should be 0)', fmt(f.balance_check_kWh, 6) + ' kWh'],
      ['Reusable heat (subset of rejected heat)', fmt(f.reusable_heat_kWh, 3) + ' kWh'], ['Its exergy (work potential above ambient)', fmt(f.reusable_exergy_kWh, 3) + ' kWh']])) + `<p class="note">${esc(f.note)}</p>`;
  }
  es.addEventListener('change', loadRuns); $('#e-run').addEventListener('change', draw);
  await loadRuns();
}
function sankey(host, links) {
  const nodes = {}; links.forEach(l => { nodes[l.source] ??= {name: l.source, in: 0, out: 0}; nodes[l.target] ??= {name: l.target, in: 0, out: 0}; nodes[l.source].out += l.kWh; nodes[l.target].in += l.kWh; });
  const col = {}; const roots = Object.keys(nodes).filter(n => !links.some(l => l.target === n)); roots.forEach(r => col[r] = 0);
  for (let it = 0; it < 10; it++) links.forEach(l => { if (col[l.source] !== undefined) col[l.target] = Math.max(col[l.target] ?? 0, col[l.source] + 1); });
  const ncol = Math.max(...Object.values(col)) + 1, W = Math.max(760, host.clientWidth || 760), H = 380, nw = 14, pad = 14;
  const total = Math.max(...Object.values(nodes).map(n => Math.max(n.in, n.out))) || 1;
  const byCol = Array.from({length: ncol}, () => []); Object.values(nodes).forEach(n => byCol[col[n.name]].push(n));
  const scale = (H - 40 - pad * 6) / (total * 1.05);
  byCol.forEach((ns, c) => { let y = 20; ns.forEach(n => { n.x = 10 + c * (W - 220) / Math.max(ncol - 1, 1); n.h = Math.max(2, Math.max(n.in, n.out) * scale); n.y = y; n.oy = y; n.iy = y; y += n.h + pad; }); });
  const colors = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)', 'var(--s5)', '#6250d6', '#008300', '#e34948'];
  let paths = '', i = 0;
  links.forEach(l => { const a = nodes[l.source], b = nodes[l.target], w = Math.max(1, l.kWh * scale);
    const y1 = a.oy + w / 2, y2 = b.iy + w / 2, x1 = a.x + nw, x2 = b.x, mx = (x1 + x2) / 2; a.oy += w; b.iy += w;
    paths += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke-width="${w}" style="stroke:${colors[i++ % colors.length]};opacity:.45"><title>${esc(l.source)} → ${esc(l.target)}: ${fmt(l.kWh, 3)} kWh</title></path>`; });
  const rects = Object.values(nodes).map(n => `<rect x="${n.x}" y="${n.y}" width="${nw}" height="${n.h}" rx="2" style="fill:var(--ink2)"></rect><text x="${n.x + nw + 6}" y="${n.y + Math.min(n.h / 2 + 4, n.h + 12)}">${esc(n.name)} · ${fmt(Math.max(n.in, n.out), 2)} kWh</text>`).join('');
  host.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="energy flow diagram">${paths}${rects}</svg>`;
}

/* ===================================================== EXPERIMENTS (2-D page) */
async function experimentsPage(host) {
  host.innerHTML = `<div class="panel"><h2>Experiment manager</h2><p class="note">Every experiment ever registered, including superseded and failed ones. New experiments go through the same validation and append-only store as the command line. <a href="/results/dashboard.html" target="_blank" rel="noopener">Open the results dashboard</a>.</p><div class="scroll" id="x-table"></div></div>
    <div class="panel" id="x-detail"><p class="muted">Select an experiment.</p></div>
    <div class="panel"><h3>Register and run a new experiment</h3>
      <p class="note">Hypothesis and evaluation criteria are frozen when the run starts. Edit the example below. Up to 2,000 runs from here; larger designs belong on the command line.</p>
      <textarea id="x-spec" rows="18" aria-label="experiment specification (JSON)"></textarea>
      <div class="row"><button class="btn primary" id="x-run" type="button">Validate, register and run</button><span id="x-msg" class="note"></span></div>
      <div class="bar-progress" aria-hidden="true"><div id="x-bar"></div></div></div>`;
  const ex = await api('/api/experiments');
  const tb = $('#x-table');
  tb.innerHTML = `<table><thead><tr><th>Key</th><th>Ver.</th><th>Status</th><th>Runs</th><th>Title</th><th>Created (UTC)</th></tr></thead><tbody>${ex.map((x, i) => `<tr data-i="${i}"><td class="mono">${esc(x.key)}</td><td>${x.version}${x.supersedes ? ' ↺' : ''}</td><td><span class="pill ${x.status === 'completed' ? 'good' : x.status === 'failed' ? 'crit' : 'warn'}">${esc(x.status)}</span></td><td class="mono">${esc(x.summary ? (x.summary.runs ?? '') : '')}</td><td>${esc(x.title)}</td><td class="mono">${esc(x.created.replace('T', ' ').replace('+00:00', ''))}</td></tr>`).join('')}</tbody></table>`;
  tb.querySelectorAll('tbody tr').forEach(tr => tr.addEventListener('click', async () => {
    tb.querySelectorAll('tr').forEach(r => r.classList.remove('sel')); tr.classList.add('sel');
    const x = ex[+tr.dataset.i]; const d = await api(`/api/experiments/${x.id}`); const s = d.spec;
    $('#x-detail').innerHTML = `<h3>${esc(x.key)} · ${esc(s.title)}</h3>` + kv([['Id', `<span class="mono">${esc(d.id)}</span>`], ['Status', esc(d.status)], ['Supersedes', esc(d.supersedes || '—')], ['Code SHA-256', `<span class="mono">${esc(d.code_sha256.slice(0, 16))}…</span>`]])
      + ['research_question', 'hypothesis', 'evaluation_criteria', 'known_limitations', 'disclosure'].filter(k => s[k]).map(k => `<p><b>${esc(k.replace(/_/g, ' '))}:</b> ${esc(s[k])}</p>`).join('')
      + `<p><a href="/api/experiments/${encodeURIComponent(x.id)}/export.csv">Download runs as CSV</a></p>`;
  }));
  $('#x-spec').value = JSON.stringify({
    key: 'X001', title: 'Example: joint vs independent in hot ambient, short run',
    research_question: 'Does joint control use less energy than independent control in a 1 h hot-ambient window?',
    hypothesis: 'Joint uses less energy per successful task than independent (paired CI below 0).',
    independent_variables: ['policy'], dependent_variables: ['E_per_success_kJ'], controlled_variables: ['workload per seed'],
    baseline: 'independent', configuration: 'S3_hot, 1 h', data_collection: 'simulator', evaluation_criteria: 'paired 95% CI',
    known_limitations: 'example only; 3 seeds',
    design: {scenarios: ['S3_hot'], policies: ['independent', 'joint'], seeds: [0, 1, 2], scenario_overrides: {duration_s: 3600, load_period_s: 3600}, timeseries_seeds: [0]},
  }, null, 2);
  $('#x-run').addEventListener('click', async () => {
    const msg = $('#x-msg'), bar = $('#x-bar'), btn = $('#x-run');
    let spec; try { spec = JSON.parse($('#x-spec').value); } catch (e) { msg.textContent = 'Not valid JSON: ' + e.message; return; }
    btn.disabled = true; msg.textContent = 'Validating…';
    try {
      const j = await api('/api/experiments', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(spec)});
      msg.textContent = `Registered; running ${j.runs} runs…`;
      const poll = async () => { const s = await api(`/api/jobs/${j.job_id}`); bar.style.width = s.total ? `${100 * s.done / s.total}%` : '5%';
        if (s.status === 'running') return setTimeout(poll, 800);
        btn.disabled = false; msg.textContent = s.status === 'completed' ? `Completed: ${s.exp_id}` : `Failed: ${s.error}`; if (s.status === 'completed') experimentsPage(host); };
      poll();
    } catch (e) { btn.disabled = false; msg.textContent = e.message; }
  });
}

/* ================================================================ tabs */
const SCENES = [cooling, facility, chip, photonic];
const TABS = [...SCENES.map(s => [s.id, s.title]), ['energy', 'Energy flow'], ['experiments', 'Experiments']];
let active3d = null;
const nav = $('#tabs');
TABS.forEach(([id, t]) => { const b = el('button', {role: 'tab', id: 't-' + id, 'aria-selected': 'false', type: 'button'}, t); b.addEventListener('click', () => show(id)); nav.appendChild(b); });
function show(id) {
  if (!TABS.some(t => t[0] === id)) id = 'cooling';
  TABS.forEach(([t]) => $('#t-' + t).setAttribute('aria-selected', t === id));
  try { history.replaceState(null, '', '#' + id); } catch (e) {}
  const sc = SCENES.find(s => s.id === id);
  $('#view3d').hidden = !sc; $('#view2d').hidden = !!sc;
  showInspector(null);
  if (sc) {
    active3d = sc; camera.position.set(...sc.view.pos); controls.target.set(...sc.view.target); controls.update();
    $('#badge').innerHTML = sc.badge; $('#legend3d').innerHTML = sc.legend(); resize(); sc.activate();
  } else {
    active3d = null; const host = $('#view2d');
    (id === 'energy' ? energyPage(host) : experimentsPage(host)).catch(e => { host.innerHTML = `<div class="panel"><p>${esc(e.message)}</p></div>`; });
  }
}
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.1);
  if (!active3d) return;
  controls.update(); active3d.tick(dt);
  renderer.render(active3d.scene, camera); labels.render(active3d.scene, camera);
});
api('/api/health').then(h => { $('#health').innerHTML = `v${esc(h.version)} · simulation core ${esc(h.core_sha256.slice(0, 10))} · results hash chain <b style="color:${h.chain_ok ? 'var(--good)' : 'var(--crit)'}">${h.chain_ok ? 'verified' : 'FAILED'}</b> (${esc(h.chain_msg)})`; })
  .catch(e => { $('#health').textContent = 'API not reachable: start it with  python -m ueic serve'; });
addEventListener('hashchange', () => { const h = (location.hash || '').slice(1); if (!$('#t-' + h) || $('#t-' + h).getAttribute('aria-selected') !== 'true') show(h); });
show((location.hash || '').slice(1));
