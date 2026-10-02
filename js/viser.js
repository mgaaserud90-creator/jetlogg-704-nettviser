/* ============================================================================
   viser.js – logikken i hendelsesviseren.

   Inndeling:
     1) småhjelpere (tid, tall, norsk tallformat)
     2) kutt (pauser + uryddig-faser) og komprimert tidsakse
     3) tegn() – bygger plottet for visningen "klippet" eller "fullt"
     4) fotnotetabeller
     5) hendelsesliste (data/index.json), søk, filvelger, drag-og-slipp

   Plottbiblioteket: plotly.js v3.5.0 fra CDN (pinnet, se viser.html).
   ========================================================================== */
(function () {
  "use strict";

  var DATA = "data/";
  var LOGO = "logo/Seabrokers_Dolomiti_RGB.svg";
  var FARGAR = {
    dybde: "#a052ad",
    uryddig: "#8c8c8c"
  };

  var modus = "klippet";     /* standard: klippet visning */
  var gjeldende = null;      /* siste lastede hendelse */
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
  /* Norsk tallformat: komma som desimaltegn. */
  function norsk(v, n) {
    var s = tall(v, n);
    return (s === "-") ? s : s.replace(".", ",");
  }
  function forteikn(v) { return (v > 0 ? "+" : (v < 0 ? "\u2212" : "")); }

  /* Escaping for HTML. Merk: vi bygger ampersand-tegnet fra et
     unicode-escape, slik at kildefila ikke selv inneholder noe som kan
     bli tolket som en HTML-enhet. */
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

  /* Teller fasen med i lengde og snittfart? Samme regel som verktøyet. */
  function tellerMed(rad) {
    return (!rad.merknad) && Number(rad.r2) >= 0.90;
  }
  function merkefarge(rad) {
    if (rad.merknad === "stopp") { return "rgba(200,120,0,0.14)"; }
    if (rad.merknad === "uryddig") { return FARGAR.uryddig; }
    return tellerMed(rad) ? "rgba(57,155,84,0.30)" : "rgba(150,150,150,0.18)";
  }

  /* ------------------------------------------------------------------ 2) */
  /* Kuttene = pausene (stopp_perioder) + uryddig-fasene (seksjoner).      */

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
    /* slå sammen overlappende intervaller, slik at fjernetFoer blir riktig */
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

  /* Hvor mange sekunder som er kuttet bort før tidspunktet t. */
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
      feil("Fila mangler feltet 'serie' – den er laget av en eldre eksportør. "
        + "Kjør eksporter_hendelser.py på nytt.");
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

    /* -- hvilke punkter blir tegnet, og hvor på aksen ---------------- */
    var keep = [];
    for (var i = 0; i < t.length; i++) {
      if (klippet && inneIEitKutt(t[i], kutt)) { continue; }
      keep.push(i);
    }
    if (!keep.length) {
      feil("Hendelsen har ingen punkter igjen etter klipping.");
      return;
    }
    function xav(i) { return klippet ? (t[i] - fjernetFoer(t[i], kutt)) : t[i]; }

    var xs = keep.map(xav);
    var klokker = keep.map(function (i) { return klokke(base + t[i] * 1000); });
    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
    if (xmax === xmin) { xmax = xmin + 1; }
    var xpad = (xmax - xmin) * 0.008;

    /* -- sporene ------------------------------------------------------ */
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

    /* -- pausene: markør med hele fotnoten i hover -------------------- */
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

    /* -- skyggelegging og merker -------------------------------------- */
    var shapes = [], annot = [];

    if (klippet) {
      /* Bruddmerke + farget stopplinje der en tid er kuttet bort. */
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
        /* (Uryddig-brudd får bare det grå bruddmerket, ikke egen tekst –
           teksten havnet oppå kurvene og gjorde plottet urolig.) */
      });
    } else {
      /* Full visning: hvert kutt blir et gjennomsiktig bånd over hele
         plottet – en pause = ett bånd, i samme farge som i fotnoten. */
      var spennT = Math.max(1, t[t.length - 1] - t[0]);
      kutt.forEach(function (k) {
        var erPause = (k.type === "pause");
        shapes.push({
          type: "rect", xref: "x", yref: "paper", x0: k.fra, x1: k.til,
          y0: 0, y1: 1, fillcolor: k.farge,
          opacity: erPause ? 0.22 : 0.13, line: { width: 0 }, layer: "below"
        });
        /* Merket blir bare satt på et bånd som er bredt nok, ellers ville
           korte bånd skrevet seg oppå hverandre helt ved toppen. */
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

    /* -- fargestripe for fasene nederst ------------------------------- */
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

    /* -- stigningstall over plottet: BARE TALL (cm/min står i fotnoten) */
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
    var antall_hoyre = kanaler.length;
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
      dragmode: "zoom",                 /* dra = rektangelzoom */
      shapes: shapes,
      annotations: annot,
      legend: { orientation: "h", y: 1.22, x: 0, font: { size: 10.5 } },
      xaxis: {
        domain: [0, 1 - BR],
        title: { text: klippet ? "Tid (pauser og uryddig tatt ut av aksen)"
                               : "Tid" },
        showgrid: true, gridcolor: "#eef1f5", zeroline: false,
        tickmode: "array", tickvals: tv.vals, ticktext: tv.texts,
        range: [xmin - xpad, xmax + xpad],
        ticks: "outside", tickcolor: "#b9c4d0"
      },
      yaxis: {
        title: { text: "Dybde [cm] (0 \u00f8verst)", font: { color: FARGAR.dybde } },
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

    Plotly.react("plott", traces, layout, {
      responsive: true, displaylogo: false, scrollZoom: true,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
      toImageButtonOptions: { filename: (valgtFil || "hendelse").replace(/\.json$/, "") }
    });
    Plotly.Plots.resize(document.getElementById("plott"));

    skrivSamandrag(d, kutt, t, klippet);
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

  /* Haker på x-aksen: jevnt fordelt over VIST tid (ikke over tallet på punkt),
     merket med klokka til det punktet haket lander på. Samplingen er tettere i
     noen partier enn andre; teller vi bare punkt, havner hakene i klynger i de
     tette partiene. Derfor styrer vi etter posisjonen på aksen. */
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

  /* -- sammendrag øverst -------------------------------------------- */
  function skrivSamandrag(d, kutt, t, klippet) {
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
      ["Utelatt", norsk(d.utelatt_pst, 1) + " % av tiden"],
      ["Pausar", String(stopp.length)]
    ];

    /* hvor mye av tiden aksen faktisk viser */
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
            + " min tatt ut: " + Math.round(pause_s / 60) + " min pause, "
            + Math.round(uryddig_s / 60) + " min uryddig)"]);
        } else {
          faktat.push(["Akse", "hele forløpet, " + Math.round(total / 60)
            + " min \u2013 pausene som fargebånd"]);
        }
      }
    }

    document.getElementById("oppsummering").innerHTML =
      faktat.map(function (p) {
        return '<span class="fakta"><b>' + p[0] + ":</b> " + p[1] + "</span>";
      }).join("");
  }

  /* ------------------------------------------------------------------ 4) */
  /* Fotnotetabellene. Innholdet er det operatøren ba om tidligere.        */

  function skrivStopptabell(d, base) {
    var stopp = d.stopp_perioder || [];
    var st = document.getElementById("stopptabell");
    var forklaring = "<p class='forklaring'>Alle fartstall i plottet er i "
      + "<b>cm/min</b> og er skrevet uten enhet (bare tall) for å holde "
      + "plottet ryddig. I Fullt-visningen ligger hver pause som et "
      + "gjennomsiktig fargebånd over plottet \u2013 ett bånd per pause, "
      + "i samme farge som raden nedenfor.</p>";

    if (!stopp.length) {
      st.innerHTML = "<h3>Pauser</h3>" + forklaring
        + "<p>Ingen pause over grensen i denne hendelsen.</p>";
      return;
    }
    st.innerHTML = "<h3>Pauser &ndash; nummerert fra dypest til grunnest "
      + "(fargen er båndet/streken i plottet; \u0394 dybde: + = gikk ned "
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
    se.innerHTML = "<h3>Faser (gr&oslash;nn = teller med i lengde og snitt, "
      + "gr&aring; = holdt utenfor)</h3>"
      + "<div class='rull'><table><tr><th>#</th><th>fra</th>"
      + "<th>til</th><th>sek</th><th>cm</th><th>cm/min</th><th>R2</th>"
      + "<th>merknad</th><th>teller</th></tr>"
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

  /* -- skriv ut / lagre bildet som står på skjermen ----------------- */

  function biletetekst() {
    return valgtFil ? valgtFil.replace(/\.json$/i, "")
      : (gjeldende && gjeldende.pel ? gjeldende.pel : "hendelse");
  }

  /* Åpner et nytt vindu med bildet, sammendraget og fotnotene, og
     ber nettleseren skrive det ut. Samme innhold som tabellene på siden. */
  function opneUtskriftsvindauge(dataUrl) {
    var w = window.open("", "_blank");
    if (!w) {
      feil("Nettleseren blokkerte utskriftsvinduet. Tillat oppsprett "
        + "for denne siden og prøv igjen.");
      return;
    }
    var sum = document.getElementById("oppsummering").innerHTML;
    var stopp = document.getElementById("stopptabell").innerHTML;
    var faser = document.getElementById("seksjonstabell").innerHTML;
    var vising = (modus === "klippet") ? "Klippet" : "Fullt";
    var namn = biletetekst();
    var html =
      '<!DOCTYPE html><html lang="nb"><head><meta charset="utf-8">'
      + '<title>JETLOGG 704 \u2013 ' + esc(namn) + '</title><style>'
      + 'body{font-family:"Segoe UI",Arial,sans-serif;margin:14px;color:#1d2430;}'
      + 'h1{font-size:16px;margin:0 0 6px;color:#00325f;}'
      + '.samandrag{font-size:12.5px;margin:0 0 10px;}'
      + '.samandrag .fakta{display:inline-block;margin-right:14px;margin-bottom:2px;}'
      + 'img{max-width:100%;border:1px solid #d7dee7;}'
      + '.tabell{font-size:11.5px;}'
      + '.tabell h3{font-size:13px;margin:12px 0 5px;}'
      + '.tabell table{border-collapse:collapse;width:100%;}'
      + '.tabell th,.tabell td{border:1px solid #d7dee7;padding:3px 6px;text-align:left;}'
      + '.tabell th{background:#f3f6fa;}'
      + '.fargeprikk{display:inline-block;width:9px;height:9px;margin-right:5px;border-radius:2px;}'
      + '.verktoystolpe{margin:0 0 10px;}'
      + '.verktoystolpe button{font:inherit;padding:7px 12px;border:1px solid #004996;background:#fff;color:#004996;border-radius:6px;font-weight:600;cursor:pointer;}'
      + '.forklaring{color:#5b6877;font-size:12px;}'
      + '@media print{.verktoystolpe{display:none;} body{margin:0;}}'
      + '</style></head><body>'
      + '<h1>JETLOGG 704 \u2013 ' + esc(namn) + ' (' + esc(vising) + ')</h1>'
      + '<div class="verktoystolpe">'
      + '<button type="button" id="lagre-png">Last ned PNG</button> '
      + '<span class="forklaring">eller bruk Ctrl+P / Cmd+P for \u00e5 skrive ut.</span>'
      + '</div>'
      + '<div class="samandrag">' + sum + '</div>'
      + '<img id="bilete" alt="Plott: ' + esc(namn) + '" src="' + dataUrl + '">'
      + '<div class="tabell">' + stopp + faser + '</div>'
      + '</body></html>';
    w.document.open();
    w.document.write(html);
    w.document.close();
    var img = w.document.getElementById("bilete");
    var lagre = w.document.getElementById("lagre-png");
    if (lagre) {
      lagre.addEventListener("click", function () {
        var a = w.document.createElement("a");
        a.href = dataUrl;
        a.download = namn + ".png";
        w.document.body.appendChild(a);
        a.click();
      });
    }
    function skriv() { try { w.focus(); w.print(); } catch (e) {} }
    if (img && !img.complete) { img.addEventListener("load", skriv); }
    else { skriv(); }
  }

  /* Renderer den AKTIVE figuren – samme visning (klippet/fullt) og samme
     levende zoom som står på skjermen. Plotly.toImage leser den gjeldende
     layouten, så eventuell rektangel-/rullezoom blir med i bildet. */
  function eksporterAktiv() {
    if (!gjeldende) {
      feil("Ingen hendelse er lastet \u2013 velg en hendelse først.");
      return;
    }
    var gd = document.getElementById("plott");
    var namn = biletetekst();
    var breidd = gd.clientWidth || 1000;
    var hogd = gd.clientHeight || 640;
    Plotly.toImage(gd, { format: "png", width: breidd, height: hogd, scale: 2 })
      .then(function (dataUrl) { opneUtskriftsvindauge(dataUrl); })
      .catch(function (err) {
        feil("Klarte ikke lage bildet: "
          + esc(err && err.message ? err.message : err));
      });
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
      treffEl.textContent = 'Ingen hendelser passer "' + sok + '". '
        + "Prøv f.eks. K83, 83, grouting eller 2026-10-01.";
      return;
    }
    html = '<option value="">Velg hendelse (' + treff.length + " av "
      + alle.length + ") \u2026</option>";
    treff.forEach(function (h) {
      html += '<option value="' + esc(h.fil) + '">' + esc(etikett(h)) + "</option>";
    });
    velg.innerHTML = html;

    treffEl.className = "treff";
    treffEl.textContent = sok
      ? (treff.length + " treff av " + alle.length + " hendelser")
      : (alle.length + " hendelser i listen");

    if (valgtFil && treff.some(function (h) { return h.fil === valgtFil; })) {
      velg.value = valgtFil;
    } else if (treff.length === 1 && sok) {
      /* et entydig treff – vis det med en gang */
      velg.value = treff[0].fil;
      hentOgVis(treff[0].fil);
    }
  }

  /* JS-tvillingene: data/index.js legger JETLOGG_INDEKS i window, og
     data/<navn>.js legger hver hendelse i window.JETLOGG_HENDELSE. De kan
     lastes med en vanlig <script src>, som OGSÅ er lovlig på file://,
     der nettleseren ellers blokkerer fetch. */
  function hendelseGlobal(navn) {
    return (window.JETLOGG_HENDELSE && window.JETLOGG_HENDELSE[navn]) || null;
  }

  function visHendelseFraGlobal(navn, vedFeil) {
    var d = hendelseGlobal(navn);
    if (d) { lesTekst(JSON.stringify(d), navn); return; }
    /* Tvillingen er ikke lastet ennå – hent den med en <script src>. */
    var s = document.createElement("script");
    s.src = DATA + navn.replace(/\.json$/i, ".js");
    s.onload = function () {
      var d2 = hendelseGlobal(navn);
      if (d2) { lesTekst(JSON.stringify(d2), navn); }
      else { vedFeil("fant ikke \u00ab" + navn + "\u00bb i de innebygde dataene"); }
    };
    s.onerror = function () {
      vedFeil("fant verken fila eller JS-tvillingen til den");
    };
    document.head.appendChild(s);
  }

  function hentOgVis(navn) {
    valgtFil = navn;
    fetch(DATA + navn, { cache: "no-store" }).then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.text();
    }).then(function (txt) { lesTekst(txt, navn); })
      .catch(function (err) {
        /* fetch kan være blokkert (typisk file://) – prøv JS-tvillingen. */
        visHendelseFraGlobal(navn, function (melding) {
          feil("Klarte ikke hente \u00ab" + esc(navn) + "\u00bb ("
            + esc(melding || err.message) + ").");
        });
      });
  }

  function lesTekst(tekst, navn) {
    var d;
    try { d = JSON.parse(tekst); }
    catch (e) {
      feil("Klarte ikke lese \u00ab" + esc(navn) + "\u00bb som JSON: " + esc(e.message));
      return;
    }
    if (d.hendelser && d.hendelser.length) {
      feil("Dette er den kombinerte fila med " + d.hendelser.length
        + " hendelser. Velg en enkelt hendelse i nedtrekksmenyen "
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
    leser.onerror = function () { feil("Klarte ikke lese fila " + esc(fil.name)); };
    leser.readAsText(fil, "utf-8");
  }

  function visIndekshint(tekst) {
    var b = document.getElementById("indekshint");
    b.innerHTML = tekst;
    b.style.display = "block";
  }

  function taImotIndeks(data) {
    indeks = (data && data.hendelser) || [];
    fyllListe();
    var fraUrl = /[?&]fil=([^&]+)/.exec(window.location.search);
    if (fraUrl) {
      valgtFil = decodeURIComponent(fraUrl[1]);
      document.getElementById("velg").value = valgtFil;
      hentOgVis(valgtFil);
      return;
    }
    /* Vis første hendelse med en gang, så man ser noe med det samme. */
    var forste = indeks.filter(function (h) { return !h.kombinert; })[0];
    if (forste) {
      document.getElementById("velg").value = forste.fil;
      hentOgVis(forste.fil);
    }
  }

  function lastIndeks() {
    fetch(DATA + "index.json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.json();
    }).then(function (data) { taImotIndeks(data); })
      .catch(function (err) {
        /* fetch er blokkert på file://. data/index.js er lastet med en
           vanlig <script src> og ligger i window.JETLOGG_INDEKS. Da virker
           nedtrekket og den første hendelsen uten noen server. */
        if (window.JETLOGG_INDEKS) {
          taImotIndeks(window.JETLOGG_INDEKS);
          visIndekshint("Nedtrekkslisten er lest fra den innebygde "
            + "<code>data/index.js</code> (siden er åpnet som lokal fil, der "
            + "nettleseren ikke l\u00e5r oss hente <code>data/index.json</code> "
            + "direkte). Alt virker som normalt.");
          return;
        }
        document.getElementById("velg").innerHTML =
          '<option value="">(hendelseslisten er ikke tilgjengelig)</option>';
        visIndekshint("<b>Hendelseslisten kunne ikke lastes.</b> Den krever at "
          + "siden blir kjørt fra en liten lokal server eller fra "
          + "Cloudflare \u2013 eller at <code>data/index.js</code> ligger ved "
          + "siden. Du kan fortsatt dra og slippe en JSON-fil hit eller bruke "
          + "\u00abÅpne JSON-fil\u00bb. (" + esc(err.message) + ")");
      });
  }

  /* -- kobling av hendelser ----------------------------------------- */
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
  document.getElementById("kn-print").addEventListener("click", eksporterAktiv);

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

  /* Djuplenke: ...viser.html?vis=fullt (eller ?vis=klippet) velger hvilken
     visning siden starter i. Standard er klippet. */
  var vm = /[?&]vis=(klippet|fullt)/i.exec(window.location.search);
  if (vm) { modus = vm[1].toLowerCase(); }
  merkBolk(modus === "klippet");

  window.visData = tegn;            /* for prøving og andre sider */
  window.jetloggModus = function () { return modus; };
  lastIndeks();
})();
