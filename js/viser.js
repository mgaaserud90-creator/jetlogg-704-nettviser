/* ============================================================================
   viser.js – logikken i hendelsesviseren.

   Inndeling:
     1) smahjelparar (tid, tal, norsk talformat)
     2) kutt (pausar + uryddig-fasar) og komprimert tidsakse
     3) tegn() – byggjer plottet for visinga "klippet" eller "fullt"
     4) fotnotetabellar
     5) hendelsesliste (data/index.json), sok, filveljar, drag-og-slipp

   Plottbiblioteket: plotly.js v3.5.0 fra CDN (pinnet, sjaa viser.html).
   ========================================================================== */
(function () {
  "use strict";

  var DATA = "data/";
  var LOGO = "logo/Seabrokers_Dolomiti_RGB.svg";
  var FARGAR = {
    dybde: "#a052ad",
    fart: "#444444",
    uryddig: "#8c8c8c"
  };

  var modus = "klippet";     /* standard: klippet vising */
  var gjeldende = null;      /* siste lasta hendelse */
  var indeks = [];           /* hendelsene fra index.json */
  var valgtFil = "";

  /* ------------------------------------------------------------------ 1) */

  function p2(x) { return (x < 10 ? "0" : "") + x; }

  function fmtTid(ms) {                       /* "YYYY-MM-DD HH:MM:SS" */
    var d = new Date(ms);
    return d.getFullYear() + "-" + p2(d.getMonth() + 1) + "-" + p2(d.getDate())
      + " " + p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":"
      + p2(d.getSeconds());
  }
  function klokke(ms) { return fmtTid(ms).slice(11, 19); }      /* HH:MM:SS */
  function klokkeKort(ms) { return fmtTid(ms).slice(11, 16); }  /* HH:MM    */

  function tall(v, n) {
    return (v === null || v === undefined || !isFinite(v)) ? "-"
      : Number(v).toFixed(n);
  }
  /* Norsk talformat: komma som desimalteikn. */
  function norsk(v, n) {
    var s = tall(v, n);
    return (s === "-") ? s : s.replace(".", ",");
  }
  function forteikn(v) { return (v > 0 ? "+" : (v < 0 ? "\u2212" : "")); }

  /* Escaping for HTML. Merk: vi byggjer ampersand-teiknet fra eit
     unicode-escape, slik at kjeldefila ikkje sjolv inneheld noko som kan
     bli tolka som ei HTML-eining. */
  var AMP = "\u0026";
  function esc(t) {
    return String(t === null || t === undefined ? "" : t)
      .replace(new RegExp(AMP, "g"), AMP + "amp;")
      .replace(/</g, AMP + "lt;")
      .replace(/>/g, AMP + "gt;")
      .replace(/"/g, AMP + "quot;");
  }

  function grenser(arr, ekstra) {
    var v = arr.filter(function (x) { return x !== null && isFinite(x); });
    if (!v.length) { return [0, 1]; }
    var lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
    if (lo === hi) { lo -= 1; hi += 1; }
    var p = (hi - lo) * (ekstra === undefined ? 0.05 : ekstra);
    return [lo - p, hi + p];
  }

  function melding(tekst, klasse) {
    var m = document.getElementById("melding");
    m.className = "ramme" + (klasse ? " " + klasse : "");
    m.innerHTML = tekst;
    m.style.display = "block";
  }
  function feil(t) { melding("<b>" + t + "</b>", "feil"); }
  function skjulMelding() {
    document.getElementById("melding").style.display = "none";
  }

  /* Fartsprofil i cm/min, positiv = stanga gar OPP. Lett median-glatta. */
  function fartsprofil(t, y) {
    var n = t.length, raa = new Array(n);
    for (var i = 1; i < n; i++) {
      var dt = t[i] - t[i - 1];
      if (dt > 0 && y[i] !== null && y[i - 1] !== null) {
        raa[i] = -(y[i] - y[i - 1]) / dt * 60;
      } else { raa[i] = null; }
    }
    raa[0] = (raa[1] === null || raa[1] === undefined) ? 0 : raa[1];
    return raa.map(function (_v, i) {
      var vinn = [];
      for (var k = Math.max(0, i - 2); k <= Math.min(n - 1, i + 2); k++) {
        if (raa[k] !== null && isFinite(raa[k])) { vinn.push(raa[k]); }
      }
      if (!vinn.length) { return null; }
      vinn.sort(function (a, b) { return a - b; });
      return vinn[Math.floor(vinn.length / 2)];
    });
  }

  /* Teller fasen med i lengde og snittfart? Same regel som verktoyet. */
  function tellerMed(rad) {
    return (!rad.merknad) && Number(rad.r2) >= 0.90;
  }
  function merkefarge(rad) {
    if (rad.merknad === "stopp") { return "rgba(200,120,0,0.14)"; }
    if (rad.merknad === "uryddig") { return FARGAR.uryddig; }
    return tellerMed(rad) ? "rgba(57,155,84,0.30)" : "rgba(150,150,150,0.18)";
  }

  /* ------------------------------------------------------------------ 2) */
  /* Kutta = pausane (stopp_perioder) + uryddig-fasane (seksjoner).        */

  function byggKutt(d, base) {
    var kutt = [];
    (d.stopp_perioder || []).forEach(function (st) {
      if (isFinite(st.fra_s) && isFinite(st.til_s) && st.til_s > st.fra_s) {
        kutt.push({ fra: st.fra_s, til: st.til_s, farge: st.farge,
                    type: "pause", nr: st.nr, varighet: st.varighet });
      }
    });
    (d.seksjoner || []).forEach(function (rad) {
      if (rad.merknad !== "uryddig") { return; }
      var f = new Date(rad.fra_iso).getTime(), tl = new Date(rad.til_iso).getTime();
      if (!isFinite(f) || !isFinite(tl) || tl <= f) { return; }
      kutt.push({ fra: (f - base) / 1000, til: (tl - base) / 1000,
                  farge: FARGAR.uryddig, type: "uryddig" });
    });
    kutt.sort(function (a, b) { return a.fra - b.fra; });
    /* sla saman overlappande intervall, slik at fjernetFoer blir rett */
    var samla = [];
    kutt.forEach(function (k) {
      var sist = samla[samla.length - 1];
      if (sist && k.fra <= sist.til) {
        sist.til = Math.max(sist.til, k.til);
        if (k.type === "pause") { sist.type = "pause"; sist.farge = k.farge; sist.nr = k.nr; sist.varighet = k.varighet; }
      } else { samla.push({ fra: k.fra, til: k.til, farge: k.farge, type: k.type, nr: k.nr, varighet: k.varighet }); }
    });
    return samla;
  }

  /* Kor mange sekund som er kutta bort for tidspunktet t. */
  function fjernetFoer(t, kutt) {
    var sum = 0;
    for (var i = 0; i < kutt.length; i++) {
      if (t <= kutt[i].fra) { break; }
      sum += Math.min(t - kutt[i].fra, kutt[i].til - kutt[i].fra);
    }
    return sum;
  }
  function inneIEitKutt(t, kutt) {
    for (var i = 0; i < kutt.length; i++) {
      if (t > kutt[i].fra && t < kutt[i].til) { return true; }
    }
    return false;
  }

  /* ------------------------------------------------------------------ 3) */

  function tegn(d, m) {
    if (!d || !d.serie || !d.serie.t_s) {
      feil("Fila manglar feltet 'serie' – ho er laga av ein eldre eksportor. "
        + "Koyr eksporter_hendelser.py pa nytt.");
      return;
    }
    gjeldende = d;
    if (m) { modus = m; }
    var klippet = (modus === "klippet");
    skjulMelding();
    merkBolk(klippet);

    var s = d.serie, t = s.t_s, dybde = s.dybde_cm, kanaler = s.kanaler || [];
    var stopp = d.stopp_perioder || [], seksjoner = d.seksjoner || [];
    var base = new Date(d.start).getTime();
    if (!isFinite(base)) { base = 0; }

    var kutt = byggKutt(d, base);

    /* -- kva punkt blir teikna, og kvar pa aksen ---------------------- */
    var keep = [];
    for (var i = 0; i < t.length; i++) {
      if (klippet && inneIEitKutt(t[i], kutt)) { continue; }
      keep.push(i);
    }
    if (!keep.length) {
      feil("Hendinga har ingen punkt att etter klipping.");
      return;
    }
    function xav(i) { return klippet ? (t[i] - fjernetFoer(t[i], kutt)) : t[i]; }

    var xs = keep.map(xav);
    var klokker = keep.map(function (i) { return klokke(base + t[i] * 1000); });
    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
    if (xmax === xmin) { xmax = xmin + 1; }
    var xpad = (xmax - xmin) * 0.008;

    /* -- spora -------------------------------------------------------- */
    var traces = [];
    traces.push({
      x: xs, y: keep.map(function (i) { return dybde[i]; }),
      name: "Dybde [cm]", mode: "lines",
      line: { color: FARGAR.dybde, width: 2 }, yaxis: "y",
      customdata: klokker,
      hovertemplate: "%{customdata} &middot; Dybde %{y:.1f} cm<extra></extra>"
    });
    kanaler.forEach(function (k, n) {
      traces.push({
        x: xs, y: keep.map(function (i) { return k.verdier[i]; }),
        name: k.etikett, mode: "lines",
        line: { color: k.farge, width: 1 }, yaxis: "y" + (n + 2),
        customdata: klokker,
        hovertemplate: "%{customdata} &middot; " + esc(k.etikett)
          + ": %{y:.2f}<extra></extra>"
      });
    });
    var fart = fartsprofil(keep.map(function (i) { return t[i]; }),
                           keep.map(function (i) { return dybde[i]; }));
    var speed_axis = kanaler.length + 2;              /* siste hogreakse */
    traces.push({
      x: xs, y: fart, name: "Fart", mode: "lines",
      line: { color: FARGAR.fart, width: 1, dash: "dot" }, yaxis: "y" + speed_axis,
      customdata: klokker,
      hovertemplate: "%{customdata} &middot; Fart %{y:.2f} cm/min<extra></extra>"
    });

    /* -- pausane: markor med heile fotnoten i hover ------------------- */
    stopp.forEach(function (st) {
      var mid = (st.fra_s + st.til_s) / 2;
      var tx = klippet ? (st.fra_s - fjernetFoer(st.fra_s, kutt)) : mid;
      var tekst = "Pause " + st.nr + " (" + (st.varighet || "") + ")<br>"
        + "stopp " + klokke(base + st.fra_s * 1000) + " / "
        + norsk(st.dybde_stopp_cm, 1) + " cm<br>"
        + "start " + klokke(base + st.til_s * 1000) + " / "
        + norsk(st.dybde_start_cm, 1) + " cm<br>"
        + "lengde " + norsk(st.lengde_cm, 1) + " cm, \u0394 dybde "
        + forteikn(st.delta_dybde_cm) + norsk(Math.abs(st.delta_dybde_cm), 1) + " cm";
      traces.push({
        x: [tx], y: [st.dybde_stopp_cm], name: "Pause " + st.nr, mode: "markers",
        marker: { color: st.farge, size: 11, symbol: "diamond" }, yaxis: "y",
        hovertext: [tekst], hoverinfo: "text", showlegend: true
      });
    });

    /* -- skyggelegging og merke --------------------------------------- */
    var shapes = [], annot = [];

    if (klippet) {
      /* Bruddmerke + farga stopplinje kor ei tid er kutta bort. */
      kutt.forEach(function (k) {
        var xp = k.fra - fjernetFoer(k.fra, kutt);
        shapes.push({
          type: "line", xref: "x", yref: "paper", x0: xp, x1: xp, y0: 0, y1: 1,
          line: { color: k.farge, width: 2, dash: "dot" }, layer: "below"
        });
        annot.push({
          x: xp, y: 1.0, xref: "x", yref: "paper", showarrow: false,
          text: (k.type === "pause") ? ("P" + k.nr) : "\u2016",
          font: { size: (k.type === "pause" ? 12 : 14), color: k.farge },
          yanchor: "bottom"
        });
        /* (Uryddig-brot far berre det grå bruddmerket, ikkje eigen tekst –
           teksten hamna oppa kurvene og gjorde plottet urolig.) */
      });
    } else {
      /* Full vising: kvart kutt blir eit gjennomsiktig band over heile
         plottet – ein pause = eitt band, i same farge som i fotnoten. */
      var spennT = Math.max(1, t[t.length - 1] - t[0]);
      kutt.forEach(function (k) {
        var erPause = (k.type === "pause");
        shapes.push({
          type: "rect", xref: "x", yref: "paper", x0: k.fra, x1: k.til,
          y0: 0, y1: 1, fillcolor: k.farge,
          opacity: erPause ? 0.22 : 0.13, line: { width: 0 }, layer: "below"
        });
        /* Merket blir berre sett pa eit band som er breitt nok, elles ville
           korte band skrive seg oppa kvarandre heilt ved toppen. */
        if (erPause || (k.til - k.fra) > 0.04 * spennT) {
          annot.push({
            x: (k.fra + k.til) / 2, y: 1.0, xref: "x", yref: "paper",
            showarrow: false,
            text: erPause ? ("P" + k.nr + " \u00b7 " + (k.varighet || "")) : "uryddig",
            font: { size: erPause ? 11 : 10, color: k.farge },
            yanchor: "bottom"
          });
        }
      });
    }

    /* -- fargestripe for fasene nedst --------------------------------- */
    seksjoner.forEach(function (rad) {
      var f = new Date(rad.fra_iso).getTime(), tl = new Date(rad.til_iso).getTime();
      if (!isFinite(f) || !isFinite(tl) || tl <= f) { return; }
      var fs = (f - base) / 1000, ts = (tl - base) / 1000;
      if (klippet && inneIEitKutt(fs, kutt) && inneIEitKutt(ts, kutt)) { return; }
      var x0 = klippet ? (fs - fjernetFoer(fs, kutt)) : fs;
      var x1 = klippet ? (ts - fjernetFoer(ts, kutt)) : ts;
      shapes.push({
        type: "rect", xref: "x", yref: "paper", x0: x0, x1: x1,
        y0: 0, y1: 0.03, fillcolor: merkefarge(rad), opacity: 1,
        line: { width: 0 }, layer: "below"
      });
    });

    /* -- fartsmerke over plottet: BARE TAL (cm/min star i fotnoten) --- */
    var merke = [];
    seksjoner.forEach(function (rad) {
      if (!tellerMed(rad)) { return; }
      var f = new Date(rad.fra_iso).getTime(), tl = new Date(rad.til_iso).getTime();
      if (!isFinite(f) || !isFinite(tl) || tl <= f) { return; }
      var fs = (f - base) / 1000, ts = (tl - base) / 1000;
      var mid = (fs + ts) / 2;
      if (klippet && inneIEitKutt(mid, kutt)) { return; }
      var xm = klippet ? (mid - fjernetFoer(mid, kutt)) : mid;
      merke.push({ x: xm, tekst: norsk(rad.cm_min, 1) });
    });
    var rader = (merke.length > 4) ? 2 : 1;
    merke.forEach(function (e, n) {
      var y = (rader === 1) ? 1.06 : (1.105 - (n % 2) * 0.058);
      annot.push({
        x: e.x, y: y, xref: "x", yref: "paper", showarrow: false,
        text: e.tekst, font: { size: 10.5, color: "#2b3947" }, yanchor: "bottom"
      });
    });

    /* -- akser -------------------------------------------------------- */
    var antall_hoyre = kanaler.length + 1;
    var BR = Math.min(0.62, Math.max(0.30, 0.058 * antall_hoyre));
    var tv = tikkar(keep, t, base, klippet, kutt);

    var layout = {
      template: "plotly_white",
      separators: ", ",                 /* norsk: komma desimal, mellomrom tusen */
      images: [{
        source: LOGO, xref: "paper", yref: "paper", x: 0.5, y: 0.5,
        sizex: 0.30, sizey: 0.22, xanchor: "center", yanchor: "middle",
        sizing: "contain", opacity: 0.07, layer: "below"
      }],
      height: 720,
      margin: { l: 64, r: 24, t: 160, b: 56 },
      hovermode: "closest",
      dragmode: "zoom",                 /* dreg = rektangelzoom */
      shapes: shapes,
      annotations: annot,
      legend: { orientation: "h", y: 1.22, x: 0, font: { size: 10.5 } },
      xaxis: {
        domain: [0, 1 - BR],
        title: { text: klippet ? "Tid (pausar og uryddig tekne ut av aksen)"
                               : "Tid" },
        showgrid: true, gridcolor: "#eef1f5", zeroline: false,
        tickmode: "array", tickvals: tv.vals, ticktext: tv.texts,
        range: [xmin - xpad, xmax + xpad],
        ticks: "outside", tickcolor: "#b9c4d0"
      },
      yaxis: {
        title: { text: "Dybde [cm] (0 \u00f8vst)", font: { color: FARGAR.dybde } },
        range: [topp(dybde), bunn(dybde)], tickfont: { color: FARGAR.dybde },
        gridcolor: "#eef1f5", zeroline: false
      }
    };
    kanaler.forEach(function (k, n) {
      layout["yaxis" + (n + 2)] = {
        title: { text: k.etikett, font: { color: k.farge } },
        range: grenser(k.verdier, 0.05),
        tickfont: { color: k.farge, size: 10 },
        overlaying: "y", side: "right", anchor: "free", showgrid: false,
        zeroline: false, ticks: "outside", ticklen: 4, tickcolor: k.farge,
        showline: true, linecolor: k.farge,
        position: (1 - BR) + BR * (n + 0.5) / antall_hoyre
      };
    });
    var gs = Math.max(1, Math.max.apply(null,
      fart.filter(function (v) { return v !== null && isFinite(v); })
          .map(function (v) { return Math.abs(v); })) * 1.15);
    layout["yaxis" + speed_axis] = {
      /* BARE "Fart" – eininga cm/min star i fotnoten. */
      title: { text: "Fart", font: { color: FARGAR.fart } },
      range: [-gs, gs], tickfont: { color: FARGAR.fart, size: 10 },
      overlaying: "y", side: "right", anchor: "free", showgrid: false,
      zeroline: true, zerolinecolor: "#cfd6de",
      ticks: "outside", ticklen: 4, tickcolor: FARGAR.fart,
      showline: true, linecolor: FARGAR.fart,
      position: (1 - BR) + BR * (kanaler.length + 0.5) / antall_hoyre
    };

    Plotly.react("plott", traces, layout, {
      responsive: true, displaylogo: false, scrollZoom: true,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
      toImageButtonOptions: { filename: (valgtFil || "hendelse").replace(/\.json$/, "") }
    });
    Plotly.Plots.resize(document.getElementById("plott"));

    skrivSamandrag(d, kutt, t, klippet, gs);
    skrivStopptabell(d, base);
    skrivFasetabell(d);
  }

  function topp(dybde) {
    var p = dybde.filter(function (v) { return v !== null && isFinite(v); });
    return p.length ? Math.max.apply(null, p) * 1.04 : 1;
  }
  function bunn(dybde) {
    var p = dybde.filter(function (v) { return v !== null && isFinite(v); });
    var b = p.length ? Math.min.apply(null, p) : 0;
    return Math.min(0, b);
  }

  /* Haker pa x-aksen: jamt fordelt over VIST tid (ikkje over talet pa punkt),
     merkte med klokka til det punktet haket landar pa. Samplinga er tettare i
     nokre parti enn andre; tel vi berre punkt, hamnar hakene i klynger i dei
     tette partia. Difor styrer vi etter posisjonen pa aksen. */
  function tikkar(keep, t, base, klippet, kutt, maks) {
    maks = maks || 10;
    var n = keep.length;
    if (!n) { return { vals: [], texts: [] }; }
    function xav(i) { return klippet ? (t[i] - fjernetFoer(t[i], kutt)) : t[i]; }
    var x0 = xav(keep[0]), x1 = xav(keep[n - 1]);
    if (x1 <= x0) {
      return { vals: [x0], texts: [klokkeKort(base + t[keep[0]] * 1000)] };
    }
    var minavstand = (x1 - x0) * 0.035;
    var vals = [], texts = [], j = 0;
    for (var k = 0; k < maks; k++) {
      var maal = x0 + (x1 - x0) * k / (maks - 1);
      while (j < n - 1 && xav(keep[j]) < maal) { j++; }
      var i = keep[j], x = xav(i);
      if (vals.length && (x - vals[vals.length - 1]) < minavstand) { continue; }
      vals.push(x);
      texts.push(klokkeKort(base + t[i] * 1000));
    }
    return { vals: vals, texts: texts };
  }

  function merkBolk(klippet) {
    var a = document.getElementById("kn-klippet");
    var b = document.getElementById("kn-fullt");
    if (!a || !b) { return; }
    a.setAttribute("aria-pressed", klippet ? "true" : "false");
    b.setAttribute("aria-pressed", klippet ? "false" : "true");
  }

  /* -- samandrag overst --------------------------------------------- */
  function skrivSamandrag(d, kutt, t, klippet, gs) {
    var stopp = d.stopp_perioder || [];
    var retning = (d.retning === "ned") ? "ned" : "opp";

    var faktat = [
      ["Pel", esc(d.pel)],
      ["Metode", esc(d.metode)],
      ["Dato", esc(d.dato)],
      ["Lengde", norsk(d.lengde_cm, 1) + " cm (" + retning + ")"],
      ["Snittfart", norsk(d.snitt_cm_min, 2) + " cm/min"],
      ["Varighet", esc(d.varighet)],
      ["Dybde", norsk(d.dybde_fra_cm, 0) + " \u2192 " + norsk(d.dybde_til_cm, 0) + " cm"],
      ["Utelatt", norsk(d.utelatt_pst, 1) + " % av tida"],
      ["Pausar", String(stopp.length)]
    ];

    /* kor mykje av tida aksen faktisk viser */
    if (t.length > 1) {
      var total = t[t.length - 1] - t[0];
      var borte = 0, pause_s = 0, uryddig_s = 0;
      kutt.forEach(function (k) {
        if (k.fra >= t[0] && k.til <= t[t.length - 1]) {
          var brukt = k.til - k.fra;
          borte += brukt;
          if (k.type === "pause") { pause_s += brukt; } else { uryddig_s += brukt; }
        }
      });
      if (borte > 0) {
        if (klippet) {
          faktat.push(["Akse", Math.round((total - borte) / 60) + " min aktiv tid av "
            + Math.round(total / 60) + " min (" + Math.round(borte / 60)
            + " min teke ut: " + Math.round(pause_s / 60) + " min pause, "
            + Math.round(uryddig_s / 60) + " min uryddig)"]);
        } else {
          faktat.push(["Akse", "heile forlopet, " + Math.round(total / 60)
            + " min \u2013 pausane som fargaband"]);
        }
      }
    }

    document.getElementById("oppsummering").innerHTML =
      faktat.map(function (p) {
        return '<span class="fakta"><b>' + p[0] + ":</b> " + p[1] + "</span>";
      }).join("");
  }

  /* ------------------------------------------------------------------ 4) */
  /* Fotnotetabellane. Innhaldet er det operatoren bad om tidlegare.       */

  function skrivStopptabell(d, base) {
    var stopp = d.stopp_perioder || [];
    var st = document.getElementById("stopptabell");
    var forklaring = "<p class='forklaring'>Alle fartstal i plottet er i "
      + "<b>cm/min</b> og er skrivne utan eining (berre tal) for a halde "
      + "plottet ryddig. I Fullt-visinga ligg kvar pause som eit "
      + "gjennomsiktig fargaband over plottet \u2013 eitt band per pause, "
      + "i same farge som raden nedanfor.</p>";

    if (!stopp.length) {
      st.innerHTML = "<h3>Pausar</h3>" + forklaring
        + "<p>Ingen pause over grensa i denne hendelsen.</p>";
      return;
    }
    st.innerHTML = "<h3>Pausar &ndash; nummererte fra djupast til grunnast "
      + "(fargen er bandet/streken i plottet; \u0394 dybde: + = gjekk ned "
      + "etter pausen)</h3>" + forklaring
      + "<div class='rull'><table><tr><th>nr</th><th>varighet</th>"
      + "<th>kl. stopp</th><th>dybde stopp</th><th>kl. start</th>"
      + "<th>dybde start</th><th>lengde</th><th>\u0394 dybde</th>"
      + "<th>grunn</th></tr>"
      + stopp.map(function (x) {
          var d2 = x.delta_dybde_cm;
          return '<tr style="color:' + x.farge + ';font-weight:600">'
            + "<td><span class='fargeprikk' style='background:" + x.farge
            + "'></span>Pause " + x.nr + "</td><td>" + esc(x.varighet) + "</td>"
            + "<td>" + klokke(base + x.fra_s * 1000) + "</td>"
            + "<td>" + norsk(x.dybde_stopp_cm, 1) + " cm</td>"
            + "<td>" + klokke(base + x.til_s * 1000) + "</td>"
            + "<td>" + norsk(x.dybde_start_cm, 1) + " cm</td>"
            + "<td>" + norsk(x.lengde_cm, 1) + " cm</td>"
            + "<td>" + forteikn(d2) + norsk(Math.abs(d2), 1) + " cm</td>"
            + "<td>" + esc(x.grunn || "") + "</td></tr>";
        }).join("") + "</table></div>";
  }

  function skrivFasetabell(d) {
    var seksjoner = d.seksjoner || [];
    var se = document.getElementById("seksjonstabell");
    if (!seksjoner.length) { se.innerHTML = ""; return; }
    se.innerHTML = "<h3>Faser (gr&oslash;n = tel med i lengd og snitt, "
      + "gr&aring; = halde utanfor)</h3>"
      + "<div class='rull'><table><tr><th>#</th><th>fra</th>"
      + "<th>til</th><th>sek</th><th>cm</th><th>cm/min</th><th>R2</th>"
      + "<th>merknad</th><th>teler</th></tr>"
      + seksjoner.map(function (rad) {
          var tel = tellerMed(rad);
          return "<tr class='" + (tel ? "" : "merket") + "'>"
            + "<td>" + esc(rad.nr) + "</td><td>" + esc(rad.fra) + "</td><td>"
            + esc(rad.til) + "</td><td>" + norsk(rad.sek, 0) + "</td><td>"
            + norsk(rad.lengde_cm, 1) + "</td><td>" + norsk(rad.cm_min, 2)
            + "</td><td>" + norsk(rad.r2, 4) + "</td><td>" + esc(rad.merknad || "")
            + "</td><td>" + (tel ? "ja" : "nei") + "</td></tr>";
        }).join("") + "</table></div>";
  }

  /* ------------------------------------------------------------------ 5) */

  function etikett(h) {
    if (h.kombinert) {
      return (h.dato || "?") + " \u00b7 kombinert (" + (h.antall || "?") + " hendelser)";
    }
    return (h.dato || "?") + " \u00b7 " + (h.pel || "?") + " \u00b7 "
      + (h.metode || "?") + " \u00b7 " + norsk(h.lengde_cm, 1) + " cm"
      + (h.stopp ? " \u00b7 " + h.stopp + " pausar" : "");
  }

  function fyllListe() {
    var velg = document.getElementById("velg");
    var sokFelt = document.getElementById("sok");
    var treffEl = document.getElementById("treff");
    var sok = (sokFelt.value || "").trim().toLowerCase();
    var sokLett = sok.replace(/[^a-z0-9]/g, "");

    var alle = indeks.filter(function (h) { return !h.kombinert; });
    var treff = alle.filter(function (h) {
      if (!sok) { return true; }
      var rad = [h.pel, h.metode, h.dato, h.fil].join(" ").toLowerCase();
      if (rad.indexOf(sok) !== -1) { return true; }
      var lett = rad.replace(/[^a-z0-9]/g, "");
      return !!sokLett && lett.indexOf(sokLett) !== -1;
    });

    var html = "";
    if (!treff.length) {
      html = '<option value="">(ingen treff)</option>';
      velg.innerHTML = html;
      treffEl.className = "treff tom";
      treffEl.textContent = 'Ingen hendelser passar "' + sok + '". '
        + "Prov t.d. K83, 83, grouting eller 2026-10-01.";
      return;
    }
    html = '<option value="">Vel hendelse (' + treff.length + " av "
      + alle.length + ") \u2026</option>";
    treff.forEach(function (h) {
      html += '<option value="' + esc(h.fil) + '">' + esc(etikett(h)) + "</option>";
    });
    velg.innerHTML = html;

    treffEl.className = "treff";
    treffEl.textContent = sok
      ? (treff.length + " treff av " + alle.length + " hendelser")
      : (alle.length + " hendelser i lista");

    if (valgtFil && treff.some(function (h) { return h.fil === valgtFil; })) {
      velg.value = valgtFil;
    } else if (treff.length === 1 && sok) {
      /* eit eintydig treff – vis det med ein gong */
      velg.value = treff[0].fil;
      hentOgVis(treff[0].fil);
    }
  }

  function hentOgVis(navn) {
    valgtFil = navn;
    fetch(DATA + navn, { cache: "no-store" }).then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.text();
    }).then(function (txt) { lesTekst(txt, navn); })
      .catch(function (err) {
        feil("Klarte ikkje hente \u00ab" + esc(navn) + "\u00bb (" + err.message + ").");
      });
  }

  function lesTekst(tekst, navn) {
    var d;
    try { d = JSON.parse(tekst); }
    catch (e) {
      feil("Klarte ikkje lese \u00ab" + esc(navn) + "\u00bb som JSON: " + esc(e.message));
      return;
    }
    if (d.hendelser && d.hendelser.length) {
      feil("Dette er den kombinerte fila med " + d.hendelser.length
        + " hendelser. Vel ei einskild hendelse i nedtrekksmenyen "
        + "(" + AMP + "lt;dato" + AMP + "gt;_" + AMP + "lt;pel" + AMP
        + "gt;_" + AMP + "lt;metode" + AMP + "gt;.json).");
      return;
    }
    tegn(d, modus);
  }

  function lesFil(fil) {
    if (!fil) { return; }
    var leser = new FileReader();
    leser.onload = function () { lesTekst(String(leser.result), fil.name); };
    leser.onerror = function () { feil("Klarte ikkje lese fila " + esc(fil.name)); };
    leser.readAsText(fil, "utf-8");
  }

  function visIndekshint(tekst) {
    var b = document.getElementById("indekshint");
    b.innerHTML = tekst;
    b.style.display = "block";
  }

  function lastIndeks() {
    fetch(DATA + "index.json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.json();
    }).then(function (data) {
      indeks = (data && data.hendelser) || [];
      fyllListe();
      var fraUrl = /[?&]fil=([^&]+)/.exec(window.location.search);
      if (fraUrl) {
        valgtFil = decodeURIComponent(fraUrl[1]);
        document.getElementById("velg").value = valgtFil;
        hentOgVis(valgtFil);
        return;
      }
      /* Vis forste hendelse med ein gong, sa ein ser noko med det same. */
      var forste = indeks.filter(function (h) { return !h.kombinert; })[0];
      if (forste) {
        document.getElementById("velg").value = forste.fil;
        hentOgVis(forste.fil);
      }
    }).catch(function (err) {
      document.getElementById("velg").innerHTML =
        '<option value="">(hendelseslista er ikkje tilgjengeleg)</option>';
      visIndekshint("<b>Hendelseslista kunne ikkje lastast.</b> Ho krev at "
        + "sida blir koyrd fra ein liten lokal server eller fra "
        + "Cloudflare \u2013 ikkje fra <code>file://</code>, der nettlesaren "
        + "blokkerer lesing av nabofilene. Du kan framleis dra og sleppe ei "
        + "JSON-fil hit eller bruke \u00abOpne JSON-fil\u00bb. ("
        + esc(err.message) + ")");
    });
  }

  /* -- kopling av hendingar ----------------------------------------- */
  document.getElementById("velg").addEventListener("change", function (e) {
    if (e.target.value) { hentOgVis(e.target.value); }
  });
  document.getElementById("sok").addEventListener("input", fyllListe);
  document.getElementById("fil").addEventListener("change", function (e) {
    lesFil(e.target.files && e.target.files[0]);
  });
  document.getElementById("kn-fil").addEventListener("click", function () {
    document.getElementById("fil").click();
  });
  document.getElementById("kn-klippet").addEventListener("click", function () {
    if (gjeldende) { tegn(gjeldende, "klippet"); }
    else { modus = "klippet"; merkBolk(true); }
  });
  document.getElementById("kn-fullt").addEventListener("click", function () {
    if (gjeldende) { tegn(gjeldende, "fullt"); }
    else { modus = "fullt"; merkBolk(false); }
  });
  document.getElementById("kn-nullstill").addEventListener("click", function () {
    if (gjeldende) { tegn(gjeldende, modus); }
  });

  window.addEventListener("dragover", function (e) {
    e.preventDefault();
    document.getElementById("dropsone").classList.add("paa");
  });
  window.addEventListener("dragleave", function (e) {
    if (e.clientX <= 0 || e.clientY <= 0) {
      document.getElementById("dropsone").classList.remove("paa");
    }
  });
  window.addEventListener("drop", function (e) {
    e.preventDefault();
    document.getElementById("dropsone").classList.remove("paa");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
      lesFil(e.dataTransfer.files[0]);
    }
  });

  /* Djuplenke: ...viser.html?vis=fullt (eller ?vis=klippet) vel kva vising
     sida startar i. Standard er klippet. */
  var vm = /[?&]vis=(klippet|fullt)/i.exec(window.location.search);
  if (vm) { modus = vm[1].toLowerCase(); }
  merkBolk(modus === "klippet");

  window.visData = tegn;            /* for proving og andre sider */
  window.jetloggModus = function () { return modus; };
  lastIndeks();
})();
