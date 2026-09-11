# ===== Sistema de diseño — panel de instrumentos ============================
# Criterio (el mismo del rediseño de la vista semanal, ver memoria del proyecto):
#   · el número manda; el cromo no compite con el dato
#   · el color SÓLO significa estado — verde/ámbar/rojo. El azul es acción, no decoración
#   · la jerarquía la hacen el tamaño, el peso y el aire; no la sombra
#   · todo lo que es igual se ve igual, y lo que no, se distingue de un vistazo
# Reemplaza al template SaaS violeta: hero degradado, hover-lift en todo y cinco
# profundidades de sombra hacían que todo pesara lo mismo y que el rojo de un
# desvío real no se destacara sobre el violeta decorativo.
def inject_global_css():
    # OJO: este bloque NO se manda con st.markdown.
    # st.markdown corre el parser de Markdown incluso con unsafe_allow_html=True, y
    # Markdown corta un bloque HTML en la PRIMERA LÍNEA EN BLANCO. Con líneas en
    # blanco entre secciones, el <style> se cerraba en la primera y todo el resto del
    # CSS salía impreso como texto arriba de la página; de paso Markdown se comía los
    # asteriscos de a pares (`[class*="css"]` quedaba `[class="css"]`, `*{...}` quedaba
    # `{{...}}`). Pasó en producción el 11/09/2026.
    # st.html (Streamlit ≥1.33) inserta HTML sin pasar por Markdown. Igual se quitan
    # las líneas en blanco antes de emitir, para que el fallback también sea seguro.
    _css = """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&family=Barlow+Condensed:wght@600;700&display=swap');

      /* ---------------------------------------------------------- tokens ---- */
      :root{
        /* superficies: papel, no blanco de quirófano */
        --paper:#fbfbf9; --surface:#ffffff; --surface-2:#f4f3f0; --surface-3:#edebe6;
        /* tinta */
        --ink:#16181d; --ink-2:#3f434d; --muted:#6b7280; --faint:#9aa0aa;
        /* líneas */
        --line:#e4e2dd; --line-2:#d2cfc8; --line-3:#b9b5ac;
        /* acción (y nada más) */
        --accent:#1d4ed8; --accent-ink:#1e40af; --accent-soft:#eef3ff;
        /* estado */
        --ok:#067647;  --ok-bg:#ecfdf3;  --ok-line:#abefc6;
        --warn:#b54708; --warn-bg:#fffaeb; --warn-line:#fedf89;
        --bad:#b42318; --bad-bg:#fef3f2; --bad-line:#fecdca;
        /* forma */
        --r:8px; --r-sm:6px; --r-lg:10px;
        --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
        /* tipografía */
        --ui:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        --num:'Barlow Condensed','IBM Plex Sans',sans-serif;
        --mono:'IBM Plex Mono',ui-monospace,'SF Mono',Menlo,monospace;
      }

      /* ------------------------------------------------------------ base ---- */
      html, body, [class*="css"], .stMarkdown, p, span, label, input, button, textarea, select{
        font-family:var(--ui);
      }
      /* dígitos de ancho fijo: las columnas de números dejan de bailar al refrescar */
      body, .stMarkdown, [data-testid="stMetric"], [data-testid="stDataFrame"],
      .kpi, .pill, table, td, th{font-variant-numeric:tabular-nums; font-feature-settings:"tnum" 1;}
      [data-testid="stAppViewContainer"]{background:var(--paper);}
      .block-container{max-width:1180px; padding-top:1.1rem; padding-bottom:3rem;}
      h1,h2,h3,h4{font-family:var(--ui); color:var(--ink); letter-spacing:-.015em; font-weight:700;}
      h1{font-size:1.5rem; line-height:1.2;} h2{font-size:1.18rem;} h3{font-size:1.02rem;}
      p, li, label{color:var(--ink-2);}
      a{color:var(--accent); text-underline-offset:2px;}
      code, .stCode, pre{font-family:var(--mono); font-size:.86em;}
      hr{border:0; border-top:1px solid var(--line); margin:var(--s5) 0;}

      /* --------------------------------------------------------- botones ---- */
      /* uno solo manda por pantalla: el primario es el único con relleno */
      .stButton>button, .stDownloadButton>button, [data-testid="stFormSubmitButton"]>button{
        border-radius:var(--r-sm); font-weight:600; font-size:.9rem;
        border:1px solid var(--line-2); background:var(--surface); color:var(--ink);
        padding:.46rem .9rem; min-height:40px; box-shadow:none;
        transition:background .12s ease, border-color .12s ease, color .12s ease;
      }
      .stButton>button:hover, .stDownloadButton>button:hover{
        background:var(--surface-2); border-color:var(--line-3); color:var(--ink); transform:none;
      }
      .stButton>button:focus-visible, .stDownloadButton>button:focus-visible{
        outline:2px solid var(--accent); outline-offset:2px;
      }
      .stButton>button[kind="primary"], [data-testid="stBaseButton-primary"],
      [data-testid="stFormSubmitButton"]>button[kind="primary"]{
        background:var(--accent); border:1px solid var(--accent); color:#fff; box-shadow:none;
      }
      .stButton>button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover{
        background:var(--accent-ink); border-color:var(--accent-ink); transform:none;
      }
      .stButton>button:disabled{opacity:.45; background:var(--surface-2);}

      /* ------------------------------------------------------- contenedor --- */
      /* La tarjeta delimita, no flota: sin sombra y sin salto al pasar el mouse.
         CUIDADO: Streamlit pone este testid en TODOS los bloques verticales, no
         sólo en los st.container(border=True). Si acá se declara `border:` o
         `background:`, se dibuja una caja alrededor de CADA columna y CADA bloque
         anidado y la pantalla queda llena de rectángulos dentro de rectángulos
         (pasó el 11/09/2026 en la bandeja HOY: caja del título adentro de la caja
         de la fila, más una caja vacía donde no había botón). Acá sólo se
         re-colorea el borde que Streamlit ya haya dibujado. */
      [data-testid="stVerticalBlockBorderWrapper"]{
        border-radius:var(--r) !important; border-color:var(--line) !important;
        box-shadow:none !important; transition:border-color .12s ease;
      }
      [data-testid="stVerticalBlockBorderWrapper"]:hover{
        border-color:var(--line-2) !important; box-shadow:none !important; transform:none;
      }
      div[data-testid="stExpander"] details{
        border-radius:var(--r); border:1px solid var(--line); background:var(--surface); overflow:hidden;
      }
      div[data-testid="stExpander"] summary{font-weight:600; color:var(--ink-2);}

      /* ----------------------------------------------------------- campos --- */
      [data-baseweb="input"], [data-baseweb="select"]>div, [data-baseweb="textarea"]{
        border-radius:var(--r-sm) !important; border-color:var(--line-2) !important;
      }
      [data-baseweb="input"]:focus-within, [data-baseweb="select"]>div:focus-within{
        border-color:var(--accent) !important; box-shadow:0 0 0 3px var(--accent-soft) !important;
      }
      [data-testid="stWidgetLabel"] p{font-size:.82rem; font-weight:600; color:var(--muted);}

      /* ------------------------------------------------------------ tabs ---- */
      .stTabs [data-baseweb="tab-list"]{gap:2px; border-bottom:1px solid var(--line);}
      .stTabs [data-baseweb="tab"]{
        border-radius:0; padding:8px 14px; font-weight:600; font-size:.9rem; color:var(--muted);
        border-bottom:2px solid transparent; margin-bottom:-1px;
      }
      .stTabs [aria-selected="true"]{color:var(--ink); background:transparent; border-bottom-color:var(--accent);}
      .stTabs [data-baseweb="tab-highlight"]{display:none;}

      /* ----------------------------------------------------------- métrica -- */
      [data-testid="stMetric"]{
        background:var(--surface); border:1px solid var(--line); border-radius:var(--r);
        padding:12px 14px; box-shadow:none;
      }
      [data-testid="stMetricValue"]{font-family:var(--num); font-size:2rem; font-weight:700; line-height:1;}
      [data-testid="stMetricLabel"] p{
        font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:var(--muted);
      }

      /* ------------------------------------------------------------ tabla --- */
      [data-testid="stDataFrame"]{border:1px solid var(--line); border-radius:var(--r); overflow:hidden;}
      [data-testid="stDataFrame"] [role="columnheader"]{
        font-size:.72rem !important; font-weight:700 !important; text-transform:uppercase;
        letter-spacing:.05em; color:var(--muted) !important; background:var(--surface-2) !important;
      }

      /* ------------------------------------------------------------ hero ---- */
      /* era un bloque degradado de 130px que no decía nada. Ahora es una faja:
         el título, quién sos y la fecha, con una regla de acento a la izquierda */
      .worms-hero{
        position:relative; background:transparent; color:var(--ink); box-shadow:none;
        border:0; border-left:3px solid var(--accent); border-radius:0;
        padding:2px 0 2px 14px; margin:0 0 var(--s4);
      }
      .worms-hero .glow{display:none;}
      .worms-hero h1{
        color:var(--ink); margin:0; font-size:1.45rem; font-weight:700; letter-spacing:-.02em; line-height:1.2;
      }
      .worms-hero p{margin:3px 0 0; color:var(--muted); font-size:.9rem; opacity:1; max-width:74ch;}
      .worms-hero .chip{
        display:inline-block; margin-top:9px; background:var(--surface); color:var(--muted);
        border:1px solid var(--line); padding:3px 9px; border-radius:var(--r-sm);
        font-size:.74rem; font-weight:600;
      }

      /* ------------------------------------------------------------- kpi ---- */
      .kpi-grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
                gap:var(--s3); margin:var(--s4) 0 var(--s2);}
      .kpi{background:var(--surface); border:1px solid var(--line); border-radius:var(--r);
           padding:12px 14px; box-shadow:none; position:relative; overflow:hidden;}
      .kpi.brand{background:var(--surface); border-color:var(--line-2);}
      .kpi .l{font-size:.68rem; text-transform:uppercase; letter-spacing:.07em;
              color:var(--muted); font-weight:700; line-height:1.3;}
      .kpi .v{font-family:var(--num); font-size:2.3rem; font-weight:700; color:var(--ink);
              line-height:1; margin-top:6px; letter-spacing:.005em;}
      .kpi .v.ok{color:var(--ok);} .kpi .v.warn{color:var(--warn);} .kpi .v.bad{color:var(--bad);}
      .kpi .s{font-size:.76rem; color:var(--muted); margin-top:5px; line-height:1.35;}
      /* barra de estado al costado: se lee el semáforo sin leer el número */
      .kpi:has(.v.ok){box-shadow:inset 3px 0 0 var(--ok);}
      .kpi:has(.v.warn){box-shadow:inset 3px 0 0 var(--warn); background:var(--warn-bg); border-color:var(--warn-line);}
      .kpi:has(.v.bad){box-shadow:inset 3px 0 0 var(--bad); background:var(--bad-bg); border-color:var(--bad-line);}

      /* -------------------------------------------------------- secciones --- */
      /* el título de sección trae su propia línea: separa sin necesidad de cajas */
      .section-title{
        display:flex; align-items:center; gap:var(--s3);
        font-family:var(--ui); font-weight:700; font-size:.74rem; text-transform:uppercase;
        letter-spacing:.09em; color:var(--muted); margin:var(--s5) 0 var(--s3); white-space:nowrap;
      }
      .section-title::after{content:""; flex:1; height:1px; background:var(--line); min-width:12px;}

      /* ------------------------------------------- la pantalla está trabajando */
      /* Dirección, 11/09/2026: "hay que confirmar muchas veces cada operación y después
         aparecen cargadas varias veces". Un click dispara un rerun de toda la app (segundos,
         porque además se vacía la caché entera); el botón no cambia de aspecto y el único
         indicador que traía Streamlit estaba oculto acá abajo, así que la persona no tiene
         forma de saber que algo pasó y vuelve a apretar. Cada apretada entra como una carga.
         Mientras el script corre: los botones no aceptan clicks y se ve que está trabajando. */
      [data-test-script-state="running"] .stButton>button,
      [data-test-script-state="running"] .stDownloadButton>button,
      [data-test-script-state="running"] [data-testid="stFormSubmitButton"]>button,
      [data-test-script-state="rerunRequested"] .stButton>button,
      [data-test-script-state="rerunRequested"] .stDownloadButton>button,
      [data-test-script-state="rerunRequested"] [data-testid="stFormSubmitButton"]>button{
        pointer-events:none; opacity:.5; cursor:progress; filter:saturate(.5);
      }
      /* y el cursor de toda la página lo dice también */
      [data-test-script-state="running"], [data-test-script-state="rerunRequested"]{cursor:progress;}

      /* ------------------------------------------------- franja de pendientes */
      /* lo que hay que hacer hoy va arriba de todo y se distingue del resto:
         regla de color a la izquierda según lo más urgente que haya */
      .franja{display:flex; align-items:center; gap:var(--s3); padding:10px 14px;
              border:1px solid var(--line); border-left:3px solid var(--line-3);
              border-radius:var(--r); background:var(--surface); margin-bottom:var(--s4);}
      .franja.bad{border-left-color:var(--bad); background:var(--bad-bg); border-color:var(--bad-line);}
      .franja.warn{border-left-color:var(--warn); background:var(--warn-bg); border-color:var(--warn-line);}
      .franja .t{font-weight:700; font-size:.95rem; color:var(--ink); line-height:1.25;}
      .franja .d{font-size:.84rem; color:var(--muted); margin-top:2px;}
      .franja .d b{color:var(--ink); font-weight:700;}

      /* ------------------------------------------------------------ varios -- */
      .mono{font-family:var(--mono); font-size:.86em; color:var(--ink-2);}
      .hint{font-size:.8rem; color:var(--faint); line-height:1.45;}

      /* ----------------------------------------------------------- pills ---- */
      .pill{display:inline-block; padding:2px 8px; border-radius:var(--r-sm);
            font-size:.72rem; font-weight:700; border:1px solid transparent;}
      .pill.ok{background:var(--ok-bg); color:var(--ok); border-color:var(--ok-line);}
      .pill.warn{background:var(--warn-bg); color:var(--warn); border-color:var(--warn-line);}
      .pill.bad{background:var(--bad-bg); color:var(--bad); border-color:var(--bad-line);}
      .pill.info{background:var(--surface-2); color:var(--ink-2); border-color:var(--line-2);}

      /* --------------------------------------------------- tiles de portada -- */
      .tile-h{font-weight:700; font-size:1rem; color:var(--ink); margin:0 0 var(--s1); line-height:1.3;}
      .tile-d{color:var(--muted); font-size:.83rem; line-height:1.45; margin:0 0 var(--s3);}
      @media (min-width:741px){ .tile-h{min-height:2.6em;} .tile-d{min-height:3.7em;} }

      /* --------------------------------------------------------- avisos ----- */
      [data-testid="stAlert"]{border-radius:var(--r); border:1px solid var(--line-2);}

      /* --------------------------------------------------------- sidebar ---- */
      section[data-testid="stSidebar"]{background:var(--surface-2); border-right:1px solid var(--line);}
      section[data-testid="stSidebar"] .stButton>button{background:var(--surface);}

      /* ------------------------------------------- cromo de Streamlit fuera -- */
      #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"]{display:none !important;}
      /* stStatusWidget NO se oculta: es el aviso de que la app está trabajando y esconderlo
         fue parte de por qué la gente apretaba Guardar varias veces. Se le da el aspecto del
         sistema y se muestra sólo mientras corre. */
      [data-testid="stStatusWidget"]{
        background:var(--surface) !important; border:1px solid var(--line-2); border-radius:var(--r-sm);
        box-shadow:none !important; font-family:var(--ui); font-size:.8rem; color:var(--ink-2);
      }
      [data-testid="stStatusWidget"] *{color:var(--ink-2) !important;}
      header[data-testid="stHeader"]{background:transparent; box-shadow:none; height:0;}

      /* ----------------------------------------------------------- login ---- */
      .login-brand{text-align:center; margin:8vh 0 var(--s5);}
      .login-brand .logo{font-size:2.2rem; line-height:1;}
      .login-brand h1{
        font-size:1.6rem; margin:var(--s3) 0 var(--s1); color:var(--ink);
        background:none; -webkit-background-clip:border-box; background-clip:border-box;
        letter-spacing:-.02em;
      }
      .login-brand p{color:var(--muted); margin:0; font-weight:500; font-size:.9rem;}
      .login-title{font-weight:700; font-size:1rem; color:var(--ink); margin-bottom:var(--s1);}

      /* ------------------------------------------------------------ móvil --- */
      @media (max-width:740px){
        .block-container{padding:.8rem .8rem 4rem;}
        h1{font-size:1.25rem;} h2{font-size:1.05rem;}
        .worms-hero{padding-left:10px; margin-bottom:var(--s3);}
        .worms-hero h1{font-size:1.15rem;}
        .worms-hero p{font-size:.84rem;}
        .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr)); gap:var(--s2);}
        .kpi{padding:10px 12px;} .kpi .v{font-size:1.85rem;}
        .section-title{margin:var(--s4) 0 var(--s2);}
        input, select, textarea{font-size:16px !important;}
        [data-testid="stMetricValue"]{font-size:1.6rem;}
        .stButton>button{min-height:44px;}
      }

      /* ------------------------------------------------------- movimiento --- */
      @media (prefers-reduced-motion:reduce){*{transition:none !important; animation:none !important;}}
    </style>
    """
    _css = "\n".join(_l for _l in _css.split("\n") if _l.strip())
    try:
        st.html(_css)
    except Exception:
        st.markdown(_css, unsafe_allow_html=True)
