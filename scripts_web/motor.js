// Motor del backtest CI/24hs vs caución (réplica en JavaScript de 04_spread_signal.py, 05_sizing.py,
// 06_modelo_a_pandas.py y de la revaluación con costo en ticks, demora entre patas e impacto por tamaño de
// 13_ejecucion.py y 15_versiones.py). Versiones de la estrategia (parámetros):
//   V1 (anterior):   ponderacion "igual", margenTicks 0
//   V2 (anterior):   ponderacion "edge",  margenTicks 0.5
//   V3 (definitiva): ponderacion "edge",  margenTicks 1, topeLiquidez true  (y la pata CI primero)
// Funciona en el navegador y en Node.
(function (raiz) {
  "use strict";

  function parametrosBase(D) {
    const p = D.parametros;
    return {
      escenario: p.escenario, reinversion: true,
      capital: p.capital, invFrac: p.inv_frac, limFrac: p.lim_frac, posBase: p.pos_base, tope: p.tope,
      ponderacion: "igual", umbralBps: 0, topeLiquidez: false, margenTicks: 0,
      costoRF: p.costo_op.RF, costoRV: p.costo_op.RV, costoCEDEAR: p.costo_op.CEDEAR, costoCaucion: p.costo_caucion,
      slippageBps: 0, ticks: 0, impacto: false, demora: 0,
      filtroPostcierre: true, filtroSincronia: true, filtroCota: true,
    };
  }

  // Señales: una fila por bucket-instrumento válido, con los cuatro edges y la dirección candidata
  function senales(D, P) {
    const F = D.filas, A = D.ancho, nFil = F.length / A;
    const col = 3 + D.escenarios.indexOf(P.escenario);
    const iDem = P.demora > 0 ? D.demoras.indexOf(P.demora) : -1;
    if (P.demora > 0 && iDem < 0) throw new Error("demora no disponible: " + P.demora);
    const costo = { RF: P.costoRF, RV: P.costoRV, CEDEAR: P.costoCEDEAR };
    const mask = (P.filtroPostcierre ? 1 : 0) | (P.filtroSincronia ? 2 : 0) | (P.filtroCota ? 4 : 0);
    const out = [];
    for (let i = 0; i < nFil; i++) {
      const o = i * A;
      const fi = F[o], bucket = F[o + 1], si = F[o + 2], pci = F[o + 3], p24 = F[o + 4], flags = F[o + 5];
      if (flags & mask) continue;
      const fe = D.fechas[fi];
      const d = fe[2], cau = fe[col];
      const f = costo[D.simbolos[si][1]];
      const s = p24 / pci - 1;
      const costoBono = f * (2 + s);
      const rCol = cau - P.costoCaucion, rTom = cau + P.costoCaucion;
      // slippage pagado por pata: bps fijos + ticks de la especie en la rueda (el impacto por tamaño se suma
      // después del sizing, porque depende del tamaño de la orden)
      const slip = P.slippageBps / 1e4 + P.ticks * D.ticks[fi][si];
      let edge1 = s - rTom * d / 365 - costoBono;
      let edge2 = rCol * d / 365 - s - costoBono;
      let edge1Col = s - rCol * d / 365 - costoBono;
      let edge2Tom = rTom * d / 365 - s - costoBono;
      if (P.margenTicks > 0) {  // margen de seguridad: el bot solo opera si el edge supera margenTicks por pata
        const c = 2 * P.margenTicks * D.ticks[fi][si];
        edge1 -= c; edge2 -= c; edge1Col -= c; edge2Tom -= c;
      }
      const c1 = edge1Col > 0 || edge1 > 0, c2 = edge2Tom > 0 || edge2 > 0;
      out.push({
        fi, bucket, si, pci, p24, p24x: iDem < 0 ? p24 : F[o + 6 + iDem], d, s, f, cau, rCol, rTom, slip,
        edge1, edge2, edge1Col, edge2Tom,
        candidata: c1 && c2 ? 3 : c1 ? 1 : c2 ? 2 : 0,
        direccion: edge1 > 0 ? 1 : edge2 > 0 ? 2 : 0,
      });
    }
    return out;
  }

  // Resultado de las dos patas del título. Sin slippage ni demora usa la forma cerrada del Modelo A;
  // si no, revalúa cada pata como el paso 13: q = N / P_CI unidades.
  function pnlPatas(x, dir, N, sExtra) {
    const s = x.slip + (sExtra || 0), f = x.f;
    if (s === 0 && x.p24x === x.p24) return dir === 2 ? -N * (x.s + f * (2 + x.s)) : N * (x.s - f * (2 + x.s));
    const q = N / x.pci;
    return dir === 1 ? q * (x.p24x * (1 - s) * (1 - f) - x.pci * (1 + s) * (1 + f))
      : q * (x.pci * (1 - s) * (1 - f) - x.p24x * (1 + s) * (1 + f));
  }

  const clave = (x) => x.fi * 10000 + x.bucket;

  function dimensionar(sig, D, P) {
    let cand = sig.filter((x) => x.candidata > 0);
    for (const x of cand) {
      const e1 = Math.max(x.edge1, x.edge1Col), e2 = Math.max(x.edge2, x.edge2Tom);
      x.edgeCand = x.candidata === 1 ? e1 : x.candidata === 2 ? e2 : Math.max(e1, e2);
    }
    if (P.umbralBps > 0) cand = cand.filter((x) => x.edgeCand > P.umbralBps / 1e4);
    const n = new Map(), suma = new Map();
    for (const x of cand) {
      const k = clave(x);
      n.set(k, (n.get(k) || 0) + 1); suma.set(k, (suma.get(k) || 0) + x.edgeCand);
    }
    const sumaRaiz = new Map();
    for (const x of cand) sumaRaiz.set(clave(x), (sumaRaiz.get(clave(x)) || 0) + Math.sqrt(Math.max(x.edgeCand, 0)));
    for (const x of cand) {
      const k = clave(x), igual = 1 / n.get(k), porEdge = x.edgeCand / suma.get(k);
      const peso = P.ponderacion === "edge" ? porEdge : P.ponderacion === "raiz" ? Math.sqrt(Math.max(x.edgeCand, 0)) / sumaRaiz.get(k)
        : P.ponderacion === "mixta" ? 0.5 * igual + 0.5 * porEdge : igual;
      x.pedido = Math.min(P.posBase * peso, P.tope) * P.capital;
      if (P.topeLiquidez) x.pedido = Math.min(x.pedido, D.topeLiquidez[x.si]);
      x.orden = x.candidata === 2 ? 0 : x.candidata === 3 ? 1 : 2;      // tomadoras primero
    }
    cand.sort((a, b) => a.fi - b.fi || a.bucket - b.bucket || a.orden - b.orden || a.si - b.si);
    const ev = [], dias = [];
    let i = 0, maxAfuera = 0, maxFaltante = 0;
    while (i < cand.length) {
      const fi = cand[i].fi;
      const afuera = new Map();
      let Ps = 0, tomo = 0, coloco = 0, nCand = 0, sinEjecutar = 0;
      for (; i < cand.length && cand[i].fi === fi; i++) {
        nCand++;
        const x = cand[i], N = x.pedido;
        // Zonas de pesos (ver 05_sizing.py): primero la zona A (compensa el saldo del bot); la B
        // (extiende el neto, que cubre el operador con caución) solo si la A se agotó y su edge es positivo.
        let dir = x.candidata;
        if (dir === 3) dir = Ps >= 0 ? 2 : 1;
        let q;
        if (dir === 2) {                  // tomo con títulos
          const disp = Math.max(P.inventario - (afuera.get(x.si) || 0), 0);
          const zonaA = Math.min(Math.max(-Ps, 0), disp);
          const qa = x.edge2Tom > 0 ? Math.min(N, zonaA) : 0;
          const okB = x.edge2 > 0 && qa >= zonaA - 1e-9;
          q = qa + (okB ? Math.min(N - qa, disp - qa) : 0);
        } else {                          // coloco con títulos
          const disp = Math.max(Ps + P.limite, 0);
          const zonaA = Math.min(Math.max(Ps, 0), disp);
          const qa = x.edge1Col > 0 ? Math.min(N, zonaA) : 0;
          const okB = x.edge1 > 0 && qa >= zonaA - 1e-9;
          q = qa + (okB ? Math.min(N - qa, disp - qa) : 0);
        }
        if (q <= 1e-6) { sinEjecutar++; continue; }
        const Pantes = Ps;
        if (dir === 2) { afuera.set(x.si, (afuera.get(x.si) || 0) + q); Ps += q; tomo += q; }
        else { afuera.set(x.si, (afuera.get(x.si) || 0) - q); Ps -= q; coloco += q; }
        maxAfuera = Math.max(maxAfuera, afuera.get(x.si));
        maxFaltante = Math.max(maxFaltante, -Ps);
        ev.push({ ...x, dir, N: q, Pantes, Pdespues: Ps });
      }
      const fe = D.fechas[fi];
      const cau = fe[3 + D.escenarios.indexOf(P.escenario)];
      dias.push({ fi, d: fe[2], rCol: cau - P.costoCaucion, rTom: cau + P.costoCaucion, tomo, coloco,
        neto: tomo - coloco, nCand, sinEjecutar });
    }
    for (const c of dias) {
      c.pnlCaucion = c.neto > 0 ? c.neto * c.rCol * c.d / 365 : c.neto * c.rTom * c.d / 365;
      c.compensado = Math.min(c.tomo, c.coloco);
    }
    return { ev, dias, maxAfuera, maxFaltante };
  }

  // Regla de la segunda entrega: cada operación se cubre sola con caución y el nocional bruto del día
  // no puede superar el capital (escala proporcional dentro del bucket)
  function reglaAnterior(sig, D, P) {
    const ev = sig.filter((x) => x.direccion > 0);
    const n = new Map();
    for (const x of ev) n.set(clave(x), (n.get(clave(x)) || 0) + 1);
    for (const x of ev) x.pedido = Math.min(P.posBase / n.get(clave(x)), P.tope) * P.capital;
    const out = [];
    let i = 0;
    while (i < ev.length) {
      const fi = ev[i].fi;
      let usado = 0;
      while (i < ev.length && ev[i].fi === fi) {
        const b = ev[i].bucket;
        let j = i, pedido = 0;
        while (j < ev.length && ev[j].fi === fi && ev[j].bucket === b) { pedido += ev[j].pedido; j++; }
        const esc = Math.min(1, Math.max(P.capital - usado, 0) / pedido);
        for (let k = i; k < j; k++) {
          const N = ev[k].pedido * esc;
          if (N > 1e-6) out.push({ ...ev[k], dir: ev[k].direccion, N });
        }
        usado += pedido * esc;
        i = j;
      }
    }
    return { ev: out, dias: [], maxAfuera: null, maxFaltante: null };
  }

  // Caución "como si" cada operación se cubriera sola (atribución por especie y regla anterior)
  function caucionSola(x) {
    return x.dir === 2 ? x.N * x.rCol * x.d / 365 : -x.N * x.rTom * x.d / 365;
  }

  function correr(D, Pin) {
    const P = Object.assign(parametrosBase(D), Pin || {});
    P.inventario = P.invFrac * P.capital;
    P.limite = P.limFrac * P.capital;
    const sig = senales(D, P);
    const r = P.reinversion ? dimensionar(sig, D, P) : reglaAnterior(sig, D, P);
    const nF = D.fechas.length;

    if (P.impacto) for (const x of r.ev) x.slip += D.ticks[x.fi][x.si] * x.N / D.topeLiquidez[x.si];
    for (const x of r.ev) {
      x.patas = pnlPatas(x, x.dir, x.N);
      x.sola = x.patas + caucionSola(x);
      if (!P.reinversion && x.slip === 0 && x.p24x === x.p24) x.sola = x.N * (x.dir === 1 ? x.edge1 : x.edge2);
    }
    const cauDia = new Float64Array(nF);
    for (const c of r.dias) cauDia[c.fi] = c.pnlCaucion;

    // resultado diario y totales
    const diario = new Float64Array(nF);
    let pnlPatasTot = 0, pnlCauTot = 0, nocTot = 0, tomoN = 0, colocoN = 0, conPerdida = 0;
    for (const x of r.ev) {
      diario[x.fi] += P.reinversion ? x.patas : x.sola;
      pnlPatasTot += x.patas;
      nocTot += x.N;
      if (x.sola < 0) conPerdida++;
      if (x.dir === 2) tomoN++; else colocoN++;
    }
    if (P.reinversion) for (let k = 0; k < nF; k++) { diario[k] += cauDia[k]; pnlCauTot += cauDia[k]; }
    else pnlCauTot = r.ev.reduce((a, x) => a + (x.sola - x.patas), 0);
    const total = pnlPatasTot + pnlCauTot;

    // curva intradiaria (patas por bucket + caución del neto al cierre de la rueda)
    const flujo = new Map();
    for (const x of r.ev) flujo.set(clave(x), (flujo.get(clave(x)) || 0) + (P.reinversion ? x.patas : x.sola));
    const colCierre = 3 + D.escenarios.length;
    if (P.reinversion) for (const c of r.dias) {
      const k = c.fi * 10000 + D.fechas[c.fi][colCierre];
      flujo.set(k, (flujo.get(k) || 0) + c.pnlCaucion);
    }
    const claves = [...flujo.keys()].sort((a, b) => a - b);
    let acum = P.capital, pico = -Infinity, ddIntra = 0, primero = true;
    for (const k of claves) {
      acum += flujo.get(k);
      if (primero) { pico = acum; primero = false; }
      pico = Math.max(pico, acum);
      ddIntra = Math.min(ddIntra, acum / pico - 1);
    }
    // curva diaria
    const curva = [];
    let v = P.capital, picoD = P.capital, ddDia = 0;
    for (let k = 0; k < nF; k++) {
      v += diario[k]; picoD = Math.max(picoD, v); ddDia = Math.min(ddDia, v / picoD - 1);
      curva.push(v);
    }

    const sum = (arr, f) => arr.reduce((a, x) => a + f(x), 0);
    const pesosTom = sum(r.dias, (c) => c.tomo), pesosCol = sum(r.dias, (c) => c.coloco);
    const comp = sum(r.dias, (c) => c.compensado);
    const netoAbs = sum(r.dias, (c) => Math.abs(c.neto));
    const diasCaucion = D.fechas.reduce((a, f) => a + f[2], 0);
    const colEsc = 3 + D.escenarios.indexOf(P.escenario);

    // por bloque
    const bloques = D.bloques.map(([id, label]) => ({ id, label, patasTomo: 0, patasColoco: 0, caucion: 0,
      opsTomo: 0, opsColoco: 0, pesosTom: 0, comp: 0, total: 0, ruedas: 0, cauMedia: 0 }));
    for (let k = 0; k < nF; k++) {
      const b = bloques[D.fechas[k][1]];
      b.ruedas++; b.cauMedia += D.fechas[k][colEsc];
    }
    for (const x of r.ev) {
      const b = bloques[D.fechas[x.fi][1]];
      const val = P.reinversion ? x.patas : x.sola;
      if (x.dir === 2) { b.patasTomo += val; b.opsTomo++; } else { b.patasColoco += val; b.opsColoco++; }
    }
    for (const c of r.dias) {
      const b = bloques[D.fechas[c.fi][1]];
      b.caucion += c.pnlCaucion; b.pesosTom += c.tomo; b.comp += c.compensado;
    }
    for (const b of bloques) {
      b.cauMedia /= b.ruedas;
      b.total = b.patasTomo + b.patasColoco + b.caucion;
      b.retorno = b.total / P.capital * 100;
      b.bpsRueda = b.total / P.capital * 1e4 / b.ruedas;
      b.compPct = b.pesosTom > 0 ? b.comp / b.pesosTom * 100 : 0;
    }

    // por especie (atribución "como si" cada operación se cubriera sola)
    const inst = D.simbolos.map(([s, cat]) => ({ simbolo: s, cat, ops: 0, tomo: 0, coloco: 0, total: 0, edges: [] }));
    for (const x of r.ev) {
      const it = inst[x.si];
      it.ops++; if (x.dir === 2) it.tomo++; else it.coloco++;
      it.total += x.sola;
      it.edges.push(x.dir === 2 ? x.edge2 : x.edge1);
    }
    for (const it of inst) {
      it.retorno = it.total / P.capital * 100;
      const e = it.edges.sort((a, b) => a - b), m = e.length;
      it.edgeMedBps = m ? (m % 2 ? e[(m - 1) / 2] : (e[m / 2 - 1] + e[m / 2]) / 2) * 1e4 : NaN;
      delete it.edges;
    }

    const retorno = total / P.capital * 100;
    return {
      P, total, retorno, tna: retorno * 365 / diasCaucion, diasCaucion,
      pnlPatas: pnlPatasTot, pnlCaucion: pnlCauTot,
      ops: r.ev.length, tomo: tomoN, coloco: colocoN, nocional: nocTot,
      opsConPerdidaPct: r.ev.length ? conPerdida / r.ev.length * 100 : 0,
      edgePondBps: nocTot > 0 ? total / nocTot * 1e4 : 0,
      pesosTom, pesosCol, compensado: comp, compPct: pesosTom > 0 ? comp / pesosTom * 100 : 0,
      caucionNeta: netoAbs, caucionBruta: pesosTom + pesosCol,
      maxAfuera: r.maxAfuera, maxFaltante: r.maxFaltante,
      diario: Array.from(diario), curva, ddIntra: ddIntra * 100, ddDiario: ddDia * 100,
      diasPos: Array.from(diario).filter((x) => x > 0).length, ruedas: nF,
      bloques, inst, eventos: r.ev, dias: r.dias,
      senales: sig.length,
      candidatas: sum(r.dias, (c) => c.nCand), sinEjecutar: sum(r.dias, (c) => c.sinEjecutar),
    };
  }

  // Slippage adicional por pata (sobre el de la configuración) que lleva el resultado a cero.
  // Bisección: las decisiones del bot no cambian con este slippage adicional.
  function equilibrio(res) {
    const f = (bps) => {
      let t = res.pnlCaucion;
      for (const x of res.eventos) t += pnlPatas(x, x.dir, x.N, bps / 1e4);
      return t;
    };
    let lo = 0, hi = 50;
    if (f(lo) <= 0) return 0;
    if (f(hi) > 0) return Infinity;
    for (let k = 0; k < 40; k++) { const m = (lo + hi) / 2; if (f(m) > 0) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }

  const API = { correr, equilibrio, parametrosBase };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.MotorCI24 = API;
})(typeof window !== "undefined" ? window : globalThis);
