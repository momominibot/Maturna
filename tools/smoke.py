"""Maturna smoke test: drives the app in headless Chromium at phone size and checks the
flows that broke in the 22 Oct 2026 review.

    python3 tools/smoke.py                 # tests this checkout
    python3 tools/smoke.py --root ../other # tests another checkout of the app

Serves the folder on a local port, blocks every other host (fonts, images), fixes the
clock in Asia/Singapore and seeds localStorage once per tab. Exits 1 if any check fails.
"""
import argparse
import datetime
import functools
import http.server
import json
import socketserver
import sys
import threading
import zoneinfo
from pathlib import Path

from playwright.sync_api import sync_playwright

SGT = zoneinfo.ZoneInfo("Asia/Singapore")
NOW = datetime.datetime(2026, 10, 22, 10, 0, tzinfo=SGT)  # a Thursday morning in Singapore
PHONE = {"width": 390, "height": 844}

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail and not ok else ""))


def edd_for(weeks, days, today=NOW.date()):
    """Due date that puts today at `weeks`w`days`d (EDD = LMP + 280 days)."""
    return (today + datetime.timedelta(days=280 - (weeks * 7 + days))).isoformat()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(root):
    handler = functools.partial(QuietHandler, directory=str(root))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/index.html"


class App:
    """One tab of the app with its own storage, clock and error log."""

    def __init__(self, browser, url, seed=None, viewport=PHONE, touch=True, now=NOW):
        self.url = url
        self.ctx = browser.new_context(viewport=viewport, device_scale_factor=2, locale="en-SG",
                                       timezone_id="Asia/Singapore", has_touch=touch)
        origin = url.rsplit("/", 1)[0]
        self.ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(origin) else r.abort())
        if seed:
            # seed once per tab: a reload must keep what the test changed
            self.ctx.add_init_script(
                "(()=>{if(sessionStorage.getItem('smoke_seeded'))return;"
                "const s=%s;for(const k in s)localStorage.setItem(k,s[k]);"
                "sessionStorage.setItem('smoke_seeded','1');})()" % json.dumps(seed))
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text)
                     if m.type == "error" and "Failed to load resource" not in m.text else None)
        self.page.clock.set_fixed_time(now)
        self.page.goto(url, wait_until="load")
        self.page.wait_for_timeout(600)

    def js(self, expr, arg=None):
        return self.page.evaluate(expr, arg)

    def text(self, sel):
        return self.js("s=>{const e=document.querySelector(s);return e?e.textContent.trim():null}", sel)

    def count(self, sel):
        return self.js("s=>document.querySelectorAll(s).length", sel)

    def tab(self, name):
        # DOM click: with Google Fonts blocked the icon ligature words overflow onto the
        # neighbouring tab and would swallow a pointer click
        self.js("n=>document.querySelector(`.bottom-nav a[data-tab=\"${n}\"]`).click()", name)
        self.page.wait_for_timeout(900)

    def current_tab(self):
        return self.js("()=>document.querySelector('.bottom-nav a.on')?.dataset.tab")

    def reload(self, now=None):
        if now:
            self.page.clock.set_fixed_time(now)
        self.page.reload(wait_until="load")
        self.page.wait_for_timeout(600)

    def swipe(self, sel, x0, x1):
        self.js("""([sel,x0,x1])=>{
          const el=document.querySelector(sel); const r=el.getBoundingClientRect(); const y=r.top+r.height/2;
          const t=x=>new Touch({identifier:1,target:el,clientX:x,clientY:y});
          el.dispatchEvent(new TouchEvent('touchstart',{touches:[t(x0)],changedTouches:[t(x0)],bubbles:true,cancelable:true}));
          el.dispatchEvent(new TouchEvent('touchend',{touches:[],changedTouches:[t(x1)],bubbles:true,cancelable:true}));
        }""", [sel, x0, x1])
        self.page.wait_for_timeout(900)

    def close(self, label):
        check(f"{label}: no page errors", not self.errors, "; ".join(self.errors)[:300])
        self.ctx.close()


def try_(fn, default=None):
    try:
        return fn()
    except Exception as e:  # a missing element on old code must fail a check, not the run
        return default if default is not None else f"error: {str(e).splitlines()[0][:120]}"


def test_weeks(browser, url):
    expect = {2: ("poppy seed", "First Trimester", 4),
              20: ("banana", "Second Trimester", 20),
              38: ("large leek", "Third Trimester", 38)}
    for weeks, (size, trimester, strip_week) in expect.items():
        label = f"week {weeks}"
        app = App(browser, url, seed={"maturna_edd": edd_for(weeks, 3)})
        hero = app.js("""()=>({n:document.getElementById('h-weeks-num').textContent.trim(),
            unit:(document.getElementById('h-weeks-unit')||document.querySelector('.hero .h-weeks small')).textContent.trim(),
            size:document.getElementById('h-week-sub').textContent,
            tri:document.getElementById('hero-trimester').textContent.trim(),
            title:document.getElementById('week-title').textContent.trim(),
            days:document.getElementById('h-days-left').textContent.trim()})""")
        check(f"{label}: hero shows {weeks} weeks 3 days", hero["n"] == str(weeks) and hero["unit"] == "weeks 3 days",
              f"{hero['n']} {hero['unit']}")
        check(f"{label}: hero size is {size}", size in hero["size"], hero["size"])
        check(f"{label}: hero trimester is {trimester}", hero["tri"] == trimester, hero["tri"])
        check(f"{label}: this-week card says Week {weeks}", hero["title"] == f"Week {weeks}", hero["title"])
        check(f"{label}: days to EDD", hero["days"] == str(280 - weeks * 7 - 3), hero["days"])
        app.tab("grow")
        strip = app.js("()=>({n:document.querySelectorAll('#weekstrip button').length,"
                       "on:document.querySelector('#weekstrip button.on')?.textContent,"
                       "tri:document.getElementById('g-trimester').textContent.trim()})")
        check(f"{label}: Grow strip has 37 weeks", strip["n"] == 37, strip["n"])
        check(f"{label}: Grow opens on week {strip_week}", strip["on"] == str(strip_week), strip["on"])
        check(f"{label}: Grow trimester matches", strip["tri"] == trimester, strip["tri"])
        app.tab("eat")
        check(f"{label}: Eat lists render", app.count("#eat-go .food") > 0 and app.count("#eat-no .food") > 0,
              app.count("#eat-go .food"))
        app.tab("checklist")
        check(f"{label}: checklist rows render", app.count("#ck-list .ck") > 0, app.count("#ck-list .ck"))
        app.tab("feed")
        check(f"{label}: pump steps render", app.count("#pump-steps .pump-step") == 6, app.count("#pump-steps .pump-step"))
        app.close(label)


def test_navigation(browser, url):
    app = App(browser, url, seed={"maturna_edd": edd_for(20, 3)})
    for t in ("grow", "home", "eat", "names", "home", "feed"):
        app.tab(t)
    check("nav: tabs still switch after visiting Home", app.current_tab() == "feed", app.current_tab())
    # a render that throws must not lock the nav either
    app.js("()=>{window.renderHome=function renderHome(){throw new Error('smoke-injected')}}")
    for t in ("home", "grow"):
        app.tab(t)
    check("nav: a failing screen render does not lock the nav", app.current_tab() == "grow", app.current_tab())
    app.errors[:] = [e for e in app.errors if "smoke-injected" not in e and "renderHome failed" not in e]
    app.close("nav")


def test_settings_edd(browser, url):
    app = App(browser, url, seed={"maturna_edd": edd_for(20, 3)})
    chip = lambda: app.js("()=>document.querySelector('#trim-chips .chip.on')?.dataset.trim")
    check("settings: Eat opens on the current trimester", chip() == "2", chip())
    app.js("()=>document.getElementById('btn-settings').click()")
    app.page.wait_for_timeout(300)
    app.page.fill("#edd-edit", edd_for(38, 3))
    app.js("()=>document.getElementById('btn-save-edd2').click()")
    app.page.wait_for_timeout(1000)
    check("settings: new due date updates the hero", app.text("#h-weeks-num") == "38", app.text("#h-weeks-num"))
    check("settings: new due date moves Eat's trimester chip", chip() == "3", chip())
    on = app.js("()=>document.querySelector('#weekstrip button.on')?.textContent")
    check("settings: new due date moves Grow's selected week", on == "38", on)
    app.close("settings")


def test_first_launch(browser, url):
    early = datetime.datetime(2026, 10, 23, 1, 0, tzinfo=SGT)
    app = App(browser, url, now=early)
    want = (early.date() + datetime.timedelta(days=266)).isoformat()
    got = app.js("()=>document.getElementById('edd-input').value")
    check("first launch: suggested due date uses the local day at 01:00 SGT", got == want, f"{got} != {want}")
    check("first launch: onboarding shows, home content hidden",
          app.js("()=>getComputedStyle(document.getElementById('onboard-empty')).display!=='none'"
                 "&&getComputedStyle(document.getElementById('home-content')).display==='none'"))
    app.close("first launch")


def test_appointments(browser, url):
    # saved out of date order and without ids, like data from the old build: the tapped
    # row's sorted position (1) differs from its stored position (2)
    seed = {"maturna_edd": edd_for(20, 3), "maturna_appts": json.dumps([
        {"name": "Glucose test", "date": "2026-12-10", "time": ""},
        {"name": "OB checkup", "date": NOW.date().isoformat(), "time": "16:30"},
        {"name": "Anatomy scan", "date": "2026-11-05", "time": ""},
    ])}
    app = App(browser, url, seed=seed)
    names = lambda: app.js("()=>[...document.querySelectorAll('#appt-list .appt-name')].map(e=>e.textContent)")
    today_cls = app.js("()=>[...document.querySelectorAll('#appt-list .appt-item')]"
                       ".find(e=>e.textContent.includes('OB checkup'))?.className")
    check("appointments: today's 16:30 visit is upcoming at 10:00", today_cls and "upcoming" in today_cls, today_cls)
    app.js("""()=>[...document.querySelectorAll('#appt-list .appt-item')]
              .find(e=>e.textContent.includes('Anatomy scan')).querySelector('.appt-del').click()""")
    app.page.wait_for_timeout(200)
    after = names()
    check("appointments: delete removes the tapped entry", sorted(after) == ["Glucose test", "OB checkup"], after)
    app.reload()
    check("appointments: deletion survives reload", sorted(names()) == ["Glucose test", "OB checkup"], names())
    # add through the inline form (no window.prompt)
    app.page.on("dialog", lambda d: d.dismiss())
    app.page.click("#appt-add")
    app.page.wait_for_timeout(300)
    form_ok = try_(lambda: app.page.is_visible("#appt-form"), False)
    check("appointments: + Add opens a form", form_ok)
    if form_ok:
        app.page.fill("#appt-name", "Growth scan")
        app.page.fill("#appt-date", "2026-11-20")
        app.page.fill("#appt-time", "09:15")
        app.page.click("#appt-save")
        app.page.wait_for_timeout(300)
    check("appointments: form adds the entry", "Growth scan" in names(), names())
    if form_ok:
        before = len(names())
        app.page.click("#appt-add")
        app.page.wait_for_timeout(200)
        app.page.fill("#appt-name", "No date")
        app.page.fill("#appt-date", "")
        app.page.click("#appt-save")
        app.page.wait_for_timeout(300)
        check("appointments: a missing date is not saved", len(names()) == before and app.page.is_visible("#appt-form"),
              names())
    else:
        check("appointments: a missing date is not saved", False, "no form")
    app.close("appointments")


def test_appointment_names_are_text(browser, url):
    evil = '<img src=x onerror="window.__xss=1"><b>Scan</b>'
    app = App(browser, url, seed={"maturna_edd": edd_for(20, 3), "maturna_appts": json.dumps([
        {"name": evil, "date": "2026-11-05", "time": ""}])})
    app.page.wait_for_timeout(300)
    r = app.js("()=>({name:document.querySelector('#appt-list .appt-name')?.textContent,"
               "tags:document.querySelectorAll('#appt-list img, #appt-list b').length, xss:window.__xss||0})")
    check("appointments: a name with HTML shows as plain text", r["name"] == evil and r["tags"] == 0 and not r["xss"], r)
    app.close("appointment names")


def test_feed_local_day(browser, url):
    early = datetime.datetime(2026, 10, 23, 2, 0, tzinfo=SGT)
    app = App(browser, url, seed={"maturna_edd": edd_for(20, 3)}, now=early)
    app.tab("feed")
    app.page.fill("#f-min", "12")
    app.page.click("#f-log")
    app.page.wait_for_timeout(800)
    app.reload(now=datetime.datetime(2026, 10, 23, 10, 0, tzinfo=SGT))
    app.tab("feed")
    app.page.wait_for_timeout(700)
    check("feed: a feed logged at 02:00 SGT still counts at 10:00",
          app.text("#f-today") == "1" and app.text("#f-minutes") == "12",
          f"{app.text('#f-today')} feeds, {app.text('#f-minutes')} min")
    app.reload(now=datetime.datetime(2026, 10, 24, 1, 0, tzinfo=SGT))
    app.tab("feed")
    app.page.wait_for_timeout(700)
    check("feed: it no longer counts the next day at 01:00", app.text("#f-today") == "0", app.text("#f-today"))
    app.close("feed")


def test_swipe(browser, url):
    app = App(browser, url, seed={"maturna_edd": edd_for(20, 3)})
    app.tab("grow")
    app.swipe("#weekstrip", 320, 80)
    check("swipe: swiping the week strip keeps the Grow tab", app.current_tab() == "grow", app.current_tab())
    order = ["home", "grow", "eat", "names", "nursery", "checklist", "feed"]
    expected = order[order.index(app.current_tab()) + 1]
    app.swipe(f"#page-{app.current_tab()} .scroll > *", 320, 80)
    check("swipe: swiping elsewhere still changes tab", app.current_tab() == expected, app.current_tab())
    app.close("swipe")


def test_contractions(browser, url):
    now_ms = int(NOW.timestamp() * 1000)
    # six 70 s contractions, one every 4 minutes, all in the last half hour
    log = [{"start": now_ms - m * 60000, "end": now_ms - m * 60000 + 70000} for m in (24, 20, 16, 12, 8, 4)]
    app = App(browser, url, seed={"maturna_edd": edd_for(39, 0), "maturna_contractions": json.dumps(log)})
    alert = lambda: app.js("()=>{const e=document.getElementById('ct-alert');"
                           "return e&&!e.hidden&&e.offsetParent!==null?{text:e.textContent.trim(),role:e.getAttribute('role')}:null}")
    a = alert()
    check("contractions: alert shows for 5+ in the last hour, ~1 min long, <=5 min apart", a, a)
    check("contractions: gap is start-to-start (4 min, not 3)", a and "4 min apart" in a["text"], a and a["text"])
    check("contractions: alert is announced (role=alert)", a and a["role"] == "alert", a and a["role"])
    app.page.wait_for_timeout(3000)
    check("contractions: alert is still there after 3 s", alert())
    app.reload()
    check("contractions: timings and alert survive reload", alert() and "6 contractions" in (app.text("#ct-sub") or ""),
          app.text("#ct-sub"))
    app.page.click("#ct-btn")
    app.page.wait_for_timeout(200)
    app.reload()
    check("contractions: a running contraction survives reload", app.text("#ct-btn") == "End contraction",
          app.text("#ct-btn"))
    app.page.click("#ct-btn")
    app.page.wait_for_timeout(200)
    check("contractions: ending it records a 7th", "7 contractions" in (app.text("#ct-sub") or ""), app.text("#ct-sub"))
    app.close("contractions")


def test_small_fixes(browser, url):
    app = App(browser, url, seed={"maturna_edd": edd_for(20, 3)})
    check("kegels: '0 sets today'", (app.text("#kg-count") or "").startswith("0 sets today"), app.text("#kg-count"))
    css = app.js("""()=>{const sel=[];for(const s of document.styleSheets){try{for(const r of s.cssRules)
        if(r.selectorText)sel.push(r.selectorText)}catch(e){}}return sel}""")
    check("css: .card.tint-peach is defined", ".card.tint-peach" in css)
    check("css: .grid3 is defined once", css.count(".grid3") == 1, css.count(".grid3"))
    app.tab("feed")
    app.page.click("#pump-start")
    app.page.wait_for_timeout(300)
    badge = app.text("#pump-steps .badge")
    check("pump: running step shows minutes left", badge == "10 min", badge)
    app.page.click("#pump-start")
    pump = try_(lambda: app.js("""()=>{
        resetPump(); startPump(); pump.deadline -= 125000; startPump();
        const paused = pump.remainMs; startPump();
        const resumed = document.getElementById('pump-ring-time').textContent; startPump();
        resetPump(); startPump(); pump.deadline = Date.now() - 3600000; pumpTick();
        const done = [pump.idx, pump.running, document.getElementById('pump-ring-time').textContent];
        startPump();
        const again = [pump.idx, document.getElementById('pump-ring-time').textContent,
                       document.querySelector('#pump-steps .badge')?.textContent];
        resetPump();
        return {paused, resumed, done, again};
    }"""))
    ok = isinstance(pump, dict)
    check("pump: pause then resume keeps the stage's time left", ok and pump["paused"] == 475000 and pump["resumed"] == "57:55",
          pump)
    check("pump: a finished session ends at 00:00", ok and pump["done"] == [6, False, "00:00"], pump)
    check("pump: starting again after a finished session starts clean",
          ok and pump["again"] == [0, "60:00", "10 min"], pump)
    app.page.click("#pump-start")
    app.reload()
    app.tab("feed")
    check("pump: a running session survives reload", app.text("#pump-start") == "Pause session", app.text("#pump-start"))
    app.page.click("#pump-start")
    app.tab("nursery")
    swatches = app.js("()=>[...document.querySelectorAll('.wall-swatch')].map(e=>getComputedStyle(e).backgroundImage)")
    check("nursery: every wall swatch shows its colour",
          len(swatches) == 6 and all("gradient" in s for s in swatches), swatches[:2])
    app.page.click('.sub-tab[data-sub="yoga"]')
    app.page.wait_for_timeout(300)
    durs = app.js("()=>[...document.querySelectorAll('.ypr-dur')].map(e=>e.textContent)")
    check("yoga: 90 s pose reads '1 min 30 s'", len(durs) > 1 and durs[1] == "1 min 30 s", durs)
    app.page.click("#yoga-play")
    breath = lambda: app.js("()=>[document.getElementById('yoga-phase').textContent,"
                            "getComputedStyle(document.getElementById('yoga-breath')).animationDuration]")
    b1 = breath()
    app.page.wait_for_timeout(4400)
    b2 = breath()
    check("yoga: breathe in for 4 s, out for 6 s like the text says",
          b1 == ["inhale", "4s"] and b2 == ["exhale", "6s"], [b1, b2])
    app.page.click("#yoga-play")
    restart = try_(lambda: app.page.evaluate("""async ()=>{
        resetYoga(); yogaState.poseIdx = YOGA_POSES.length-1; yogaState.timeLeft = 1; startYoga();
        await new Promise(r=>setTimeout(r,1400));
        const done = !yogaState.running;
        startYoga();
        const r = {done, idx:yogaState.poseIdx, name:document.getElementById('yoga-name').textContent};
        resetYoga();
        return r;
    }"""))
    check("yoga: restarting a finished flow starts at pose 1",
          isinstance(restart, dict) and restart["done"] and restart["idx"] == 0, restart)
    frames = app.js("""()=>{const n=[];for(const s of document.styleSheets){try{for(const r of s.cssRules)
        if(r.type===CSSRule.KEYFRAMES_RULE)n.push(r.name)}catch(e){}}return n}""")
    check("css: slideUp keyframes are defined", "slideUp" in frames)
    app.close("small fixes")


def test_desktop_frame(browser, url):
    app = App(browser, url, seed={"maturna_edd": edd_for(20, 3)}, viewport={"width": 1280, "height": 800}, touch=False)
    geo = lambda: app.js("""()=>{const r=e=>e.getBoundingClientRect();const a=document.querySelector('.app');
        const A=r(a),T=r(document.querySelector('.top')),N=r(document.querySelector('.bottom-nav'));
        return {A:[A.left,A.top,A.right,A.bottom],T:[T.left,T.top,T.right,T.bottom],N:[N.left,N.top,N.right,N.bottom],
                sh:a.scrollHeight,ch:a.clientHeight,st:a.scrollTop,vh:innerHeight}}""")
    g = geo()
    inside = lambda b, A: b[0] >= A[0] - 1 and b[2] <= A[2] + 1 and b[1] >= A[1] - 1 and b[3] <= A[3] + 1
    check("desktop: frame fits the 800 px window", g["A"][3] <= g["vh"], g["A"])
    check("desktop: top bar sits inside the frame", inside(g["T"], g["A"]), [g["T"], g["A"]])
    check("desktop: nav sits inside the frame", inside(g["N"], g["A"]), [g["N"], g["A"]])
    app.page.mouse.move(640, 400)
    app.page.mouse.wheel(0, 900)
    app.page.wait_for_timeout(600)
    g2 = geo()
    check("desktop: content scrolls inside the frame", g2["sh"] > g2["ch"] and g2["st"] > 0, [g2["sh"], g2["ch"], g2["st"]])
    check("desktop: nav stays at the frame bottom while scrolled",
          inside(g2["N"], g2["A"]) and abs(g2["N"][3] - g2["A"][3]) <= 2, [g2["N"], g2["A"]])
    app.close("desktop")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    root = Path(ap.parse_args().root).resolve()
    httpd, url = serve(root)
    print(f"Maturna smoke test: {root}\n")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for t in (test_weeks, test_navigation, test_settings_edd, test_first_launch, test_appointments,
                  test_appointment_names_are_text, test_feed_local_day, test_swipe,
                  test_contractions, test_small_fixes, test_desktop_frame):
            try:
                t(browser, url)
            except Exception as e:
                check(f"{t.__name__} ran to the end", False, str(e).splitlines()[0][:200])
        browser.close()
    httpd.shutdown()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
