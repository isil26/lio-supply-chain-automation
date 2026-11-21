"""Check a deployed Soony team replay over HTTPS without logging credentials or case records."""
import argparse
import json
import re
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(condition, message):
    if not condition:
        raise SystemExit(f"Verification failed: {message}")


def verify(base, password):
    def client():
        return build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())

    def request(opener, path, *, expected=200, body=None, content_type="application/json", origin=None, cookie=None):
        headers = {}
        if body is not None:
            headers.update({"Content-Type": content_type, "Origin": origin or base})
        if cookie:
            headers["Cookie"] = cookie
        request = Request(base + path, data=body, headers=headers)
        try:
            response = opener.open(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            check(response.status == expected, f"{path} returned HTTP {response.status}, expected {expected}")
            return response.headers, response.read()

    anonymous, signed_in, second_user = (client() for _ in range(3))
    headers, body = request(anonymous, "/")
    check(b"Team password" in body and b'/assets/' not in body, "anonymous visitors did not see the team sign-in")
    check("no-store" in headers.get("Cache-Control", ""), "login response is cacheable")
    check(headers.get("Referrer-Policy") == "same-origin", "login page must preserve the origin on dashboard form submissions")
    request(anonymous, "/api/dashboard", expected=401)
    request(anonymous, "/api/sync", body=b"{}", expected=401)
    request(anonymous, "/api/replay/reset", body=b"{}", expected=401)
    request(anonymous, "/replay.enc", expected=404)
    request(anonymous, "/control/replay.enc", expected=404)
    request(anonymous, "/snapshot/before.json", expected=404)
    request(anonymous, "/snapshot/after.json", expected=404)

    def login(opener, value, expected):
        return request(opener, "/login", expected=expected, body=urlencode({"password": value}).encode(),
                       content_type="application/x-www-form-urlencoded")[0]

    check(not login(anonymous, "incorrect", 401).get("Set-Cookie"), "an invalid password issued a session")
    headers = login(signed_in, password, 303)
    login(second_user, password, 303)
    cookie = headers.get("Set-Cookie", "")
    check(all(flag in cookie for flag in ("__Host-soony-replay=", "Secure", "HttpOnly", "SameSite=Strict")),
          "the session cookie is missing security attributes")
    forged = cookie.partition(";")[0].replace(".before.", ".after.", 1)
    request(anonymous, "/api/dashboard", expected=401, cookie=forged)
    request(signed_in, "/api/sync", expected=403, body=b"{}", origin="https://invalid.example")

    _, shell = request(signed_in, "/")
    asset = re.search(rb'<script[^>]+src="(/assets/[^" ]+\.js)"', shell)
    check(asset is not None, "authenticated visitors did not receive the React dashboard")
    _, bundle = request(signed_in, asset[1].decode())
    check(b"Process drop" in bundle and b"TEAM REPLAY" in bundle and b"Mock source evidence" not in bundle,
          "the deployed UI bundle is missing the hosted replay controls or includes the sample client")

    def snapshot(opener):
        headers, body = request(opener, "/api/dashboard")
        check("no-store" in headers.get("Cache-Control", ""), "private forecasts are cacheable")
        return json.loads(body)

    before = snapshot(signed_in)
    check(before["sync"]["mode"] == "hosted-replay" and before["sync"]["pendingDrop"] > 0,
          "the baseline lacks a staged supplier drop")
    before_gaps = {risk["id"]: risk["gap"] for risk in before["risks"]}
    request(signed_in, "/api/sync", body=b"{}")
    after = snapshot(signed_in)
    after_gaps = {risk["id"]: risk["gap"] for risk in after["risks"]}
    check(after["sync"]["pendingDrop"] == 0, "the supplier drop did not clear")
    check(after_gaps != before_gaps, "component shortfall forecasts did not change")
    def forecasts(view):
        return {row["edition"]: tuple(row[key] for key in ("p10", "p50", "p90", "probability"))
                for row in view["readiness"]}

    initial_forecast, updated_forecast = forecasts(before), forecasts(after)
    check(initial_forecast.keys() == updated_forecast.keys() and all(
        initial_forecast[edition] != updated_forecast[edition] for edition in initial_forecast
    ), "at least one edition forecast did not change")
    primary = (after["approval"] or {}).get("title", "")
    check("art book" in primary.lower() and primary not in {option["title"] for option in before["options"]},
          "the art-book recovery option did not appear as the dashboard recommendation")
    check(snapshot(second_user)["sync"]["pendingDrop"] == before["sync"]["pendingDrop"],
          "one user's replay changed another user's baseline")
    request(signed_in, "/api/replay/reset", body=b"{}")
    check(snapshot(signed_in)["readiness"] == before["readiness"], "reset did not restore the baseline")
    request(signed_in, "/api/dashboard", expected=401, cookie=forged)
    request(second_user, "/logout", expected=303, body=b"")
    request(second_user, "/api/dashboard", expected=401)
    print("Verified team sign-in, private API and React bundle, supplier-drop forecast change, art-book recovery option, independent sessions, reset and sign-out.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("password_file", type=Path)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme != "https" or not url.hostname or url.path not in ("", "/") or any((url.query, url.fragment, url.username, url.password)):
        parser.error("URL must be an HTTPS origin")
    verify(args.url.rstrip("/"), args.password_file.read_text().strip())


if __name__ == "__main__":
    main()
