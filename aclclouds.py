import time
import os
import json
import re
import random
import requests

# 智能环境配置：仅在未设置时才应用默认值
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":1"

if "XAUTHORITY" not in os.environ:
    if os.path.exists("/home/headless/.Xauthority"):
        os.environ["XAUTHORITY"] = "/home/headless/.Xauthority"

print(f"[DEBUG] Env DISPLAY: {os.environ.get('DISPLAY')}")
print(f"[DEBUG] Env XAUTHORITY: {os.environ.get('XAUTHORITY')}")

from seleniumbase import SB

# ================= 配置区域 =================
PROXY_URL = os.getenv("PROXY", "")
COOKIE = os.getenv("COOKIE")  # 方案A JSON: {"__Host-aclclouds":"...","XSRF-TOKEN":"..."}
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# 必须用 dash 子域（__Host- cookie 仅对当前 host 生效）
BASE_HOST = "https://dash.aclclouds.com"
LOGIN_URL = f"{BASE_HOST}/auth/login"
CHECK_URL = f"{BASE_HOST}/api/client"
PROJECT_URL = f"{BASE_HOST}/projects"
# ===========================================


class AclcloudsRenewal:
    def __init__(self):
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        self.screenshot_dir = os.path.join(self.BASE_DIR, "artifacts")
        if not os.path.exists(self.screenshot_dir):
            os.makedirs(self.screenshot_dir)

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [INFO] {msg}", flush=True)

    def human_wait(self, min_s=6, max_s=10):
        time.sleep(random.uniform(min_s, max_s))

    def move_mouse_human(self, sb):
        try:
            for _ in range(3):
                sb.slow_click("body", force=True)
                time.sleep(random.uniform(0.5, 1.2))
        except Exception:
            pass

    def send_telegram_notify(self, message, photo_path=None):
        if not TG_TOKEN or not TG_CHAT_ID:
            self.log("⚠️ 未配置 TG_TOKEN 或 TG_CHAT_ID，跳过推送。")
            return
        try:
            if photo_path and os.path.exists(photo_path):
                url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
                with open(photo_path, "rb") as f:
                    requests.post(
                        url,
                        data={"chat_id": TG_CHAT_ID, "caption": message},
                        files={"photo": f},
                        timeout=30,
                    )
            else:
                url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
                requests.post(
                    url,
                    data={"chat_id": TG_CHAT_ID, "text": message},
                    timeout=30,
                )
            self.log("✅ TG 推送已发送")
        except Exception as e:
            self.log(f"❌ TG 推送失败: {e}")

    def save_debug(self, sb, name):
        path = os.path.join(self.screenshot_dir, f"{name}.png")
        try:
            sb.save_screenshot(path)
            html_path = os.path.join(self.screenshot_dir, f"{name}.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(sb.get_page_source())
            self.log(f"📎 调试截图: {path}")
            self.log(f"📎 调试 HTML: {html_path}")
            try:
                self.log(f"📎 当前 URL: {sb.get_current_url()}")
                self.log(f"📎 页面标题: {sb.get_title()}")
            except Exception:
                pass
            return path
        except Exception as e:
            self.log(f"保存调试信息失败: {e}")
            return None

    def parse_cookies(self):
        if not COOKIE:
            raise RuntimeError("环境变量 COOKIE 未设置")

        raw = COOKIE.strip().strip('"').strip("'")
        cookies = []

        if raw.startswith("{"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"COOKIE JSON 解析失败: {e}") from e
            if not isinstance(data, dict) or not data:
                raise RuntimeError(
                    'COOKIE JSON 必须是非空对象，例如 '
                    '{"__Host-aclclouds":"...","XSRF-TOKEN":"..."}'
                )
            for name, value in data.items():
                if value is None or str(value).strip() == "":
                    self.log(f"⚠️ 跳过空 cookie: {name}")
                    continue
                cookies.append((str(name), str(value).strip()))
        else:
            cookies.append(("__Host-aclclouds", raw))

        names = [n for n, _ in cookies]
        if "__Host-aclclouds" not in names:
            self.log("⚠️ COOKIE 中未包含 __Host-aclclouds，登录可能失败")
        if "XSRF-TOKEN" not in names:
            self.log("⚠️ COOKIE 中未包含 XSRF-TOKEN，部分接口可能失败")

        self.log(f"将注入 Cookie: {', '.join(names)}")
        return cookies

    def inject_cookies(self, sb):
        """在 dash.aclclouds.com 上注入会话 Cookie"""
        cookies = self.parse_cookies()

        self.log("🔗 访问 dash 登录页（挂载 Cookie 域）...")
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=25)
        time.sleep(2)

        # 若被重定向到非 dash 域，强制回 dash
        cur = sb.get_current_url()
        self.log(f"登录页当前 URL: {cur}")
        if "dash.aclclouds.com" not in cur:
            self.log("⚠️ 未停在 dash 域，强制打开 LOGIN_URL")
            sb.open(LOGIN_URL)
            time.sleep(2)

        try:
            sb.delete_all_cookies()
        except Exception:
            pass

        for name, value in cookies:
            c = {
                "name": name,
                "value": value,
                "path": "/",
                "secure": True,
            }
            # __Host- 禁止设置 domain
            if not name.startswith("__Host-"):
                c["domain"] = "dash.aclclouds.com"

            try:
                sb.add_cookie(c)
                self.log(f"✅ 已注入: {name}")
            except Exception as e:
                self.log(f"❌ 注入失败 {name}: {e}")
                if name.startswith("__Host-"):
                    sb.add_cookie({
                        "name": name,
                        "value": value,
                        "path": "/",
                        "secure": True,
                    })
                    self.log(f"✅ 重试注入成功: {name}")
                else:
                    raise

        self.log("✅ Cookie 注入完成")
        time.sleep(1)

    def assert_on_dash_projects(self, sb):
        """确保停在 dash 项目页，而不是主站 404"""
        url = sb.get_current_url()
        title = ""
        try:
            title = sb.get_title() or ""
        except Exception:
            pass

        self.log(f"当前 URL: {url}")
        self.log(f"页面标题: {title}")

        # 主站 /projects 是 404（你这次日志就是这个）
        if "dash.aclclouds.com" not in url:
            photo = self.save_debug(sb, "wrong_host")
            self.send_telegram_notify(
                f"❌ 打开了错误域名（非 dash）\nURL: {url}\nTitle: {title}",
                photo,
            )
            raise RuntimeError(
                f"期望 dash.aclclouds.com，实际: {url}。"
                "主站 aclclouds.com/projects 是 Not Found。"
            )

        if "/auth/login" in url or url.rstrip("/").endswith("/login"):
            photo = self.save_debug(sb, "not_logged_in")
            self.send_telegram_notify(
                "❌ Cookie 无效或已过期，仍在登录页。请更新 Secrets.COOKIE",
                photo,
            )
            raise RuntimeError("Cookie 无效或已过期，仍在登录页")

        bad_titles = ("not found", "404", "page not found")
        if any(t in title.lower() for t in bad_titles):
            photo = self.save_debug(sb, "page_not_found")
            self.send_telegram_notify(
                f"❌ 项目页 Not Found\nURL: {url}\nTitle: {title}",
                photo,
            )
            raise RuntimeError(f"项目页 Not Found: {url} / {title}")

        # 正文里常见 404 文案
        try:
            body = sb.get_text("body")[:500].lower()
            if "not found" in body and "project" not in body:
                # 宽松判断：标题已过则这里再兜底
                pass
        except Exception:
            pass

    def ensure_logged_in(self, sb):
        """打开 dash 项目页并确认登录有效"""
        self.log(f"打开项目页: {PROJECT_URL}")
        sb.uc_open_with_reconnect(PROJECT_URL, reconnect_time=25)
        time.sleep(3)

        # 若被跳到主站，强制再开一次 dash（不跟坏跳转）
        url = sb.get_current_url()
        if "dash.aclclouds.com" not in url:
            self.log(f"⚠️ 被重定向到: {url}，强制重新打开 dash 项目页")
            sb.open(PROJECT_URL)
            time.sleep(3)

        self.assert_on_dash_projects(sb)

        if sb.is_element_visible("text=Anti-bot confirmation"):
            self.log("检测到人机验证页，尝试处理...")
            for i in range(10):
                self.run_crack(sb, i)
                time.sleep(2)
                if not sb.is_element_visible("text=Anti-bot confirmation"):
                    break
            time.sleep(3)
            self.assert_on_dash_projects(sb)

        # API 探测（仅作辅助；页面 404 时不能只靠这个）
        try:
            api_status = sb.execute_script(
                """
                try {
                    var xhr = new XMLHttpRequest();
                    xhr.open('GET', '/api/client', false);
                    xhr.withCredentials = true;
                    xhr.send(null);
                    return xhr.status;
                } catch (e) {
                    return -1;
                }
                """
            )
            self.log(f"API /api/client 状态码: {api_status}")
            if api_status == 401:
                photo = self.save_debug(sb, "api_401")
                self.send_telegram_notify(
                    "❌ API 返回 401，登录态无效，请更新 COOKIE",
                    photo,
                )
                raise RuntimeError("API 返回 401，登录态无效")
        except RuntimeError:
            raise
        except Exception as e:
            self.log(f"API 登录探测跳过: {e}")

        # 额外确认：页面应出现 My Projects / 项目相关文案
        ready_texts = [
            "My Projects",
            "Total Projects",
            "Create Project",
            "Expires",
            "Manage",
        ]
        page_ok = False
        for t in ready_texts:
            try:
                if sb.is_text_visible(t):
                    page_ok = True
                    self.log(f"✅ 页面关键字命中: {t}")
                    break
            except Exception:
                pass

        if not page_ok:
            # 再等一会 SPA 渲染
            time.sleep(5)
            for t in ready_texts:
                try:
                    if sb.is_text_visible(t):
                        page_ok = True
                        self.log(f"✅ 延迟后关键字命中: {t}")
                        break
                except Exception:
                    pass

        if not page_ok:
            photo = self.save_debug(sb, "projects_not_ready")
            raise RuntimeError(
                "已在 dash 域但未识别到项目页内容，可能是前端未加载或 Cookie 权限不足。"
                "请查看 artifacts/projects_not_ready.html"
            )

    def get_expiry_time(self, sb, timeout=25):
        """多策略读取过期时间（兼容 class 改版 / 法语文案 7j 4h）"""
        css_selectors = [
            ".projects-card-expiry .projects-expiry-value",
            ".projects-expiry-value",
            ".projects-card-expiry",
            "[class*='projects-expiry']",
            "[class*='expiry-value']",
            "[class*='expiry']",
        ]

        deadline = time.time() + timeout
        while time.time() < deadline:
            # 1) CSS
            for sel in css_selectors:
                try:
                    if sb.is_element_visible(sel):
                        text = sb.get_text(sel).strip()
                        if text:
                            self.log(f"过期时间 CSS 命中: {sel} -> {text}")
                            return text
                except Exception:
                    pass

            # 2) 文案：Expires in / 7j 4h
            try:
                found = sb.execute_script(
                    r"""
                    const body = document.body ? document.body.innerText : '';
                    // 例如: Expires in\n7j 4h  或  Expires in 7j 4h
                    let m = body.match(/Expires\s*in\s*([0-9]+\s*[jdhm]\s*[0-9]*\s*[jdhm]?)/i);
                    if (m) return m[1].trim();
                    m = body.match(/([0-9]+\s*j\s*[0-9]+\s*h)/i);
                    if (m) return m[1].trim();
                    m = body.match(/([0-9]+d\s*[0-9]+h)/i);
                    if (m) return m[1].trim();
                    return null;
                    """
                )
                if found:
                    self.log(f"过期时间文案命中: {found}")
                    return found
            except Exception:
                pass

            time.sleep(1)

        self.save_debug(sb, "no_expiry_element")
        raise RuntimeError(
            "找不到过期时间元素。请查看 artifacts/no_expiry_element.html"
        )

    def run_crack(self, sb, i):
        if not sb.is_element_visible("text=Anti-bot confirmation"):
            return True
        buttons = sb.find_elements("css=button")
        if len(buttons) > 0:
            try:
                buttons[0].click()
            except Exception:
                pass
            return False
        return False

    def close_modal_if_any(self, sb):
        try:
            sb.execute_script(
                """
                let btns = [...document.querySelectorAll('button')];
                let closeBtn = btns.find(b => b.innerText && b.innerText.includes('Close'));
                if (closeBtn) closeBtn.click();
                """
            )
        except Exception:
            pass

    def run(self):
        self.log("=" * 40)
        self.log("🚀 Aclclouds - Renew流程")
        self.log("=" * 40)
        self.log("🎯 正在启动 Chrome 浏览器...")
        self.log(f"目标主机: {BASE_HOST}")

        if not COOKIE:
            self.log("❌ 环境变量 COOKIE 未设置")
            return

        with SB(
            uc=True,
            test=True,
            headed=True,
            headless=False,
            xvfb=False,
            chromium_arg=(
                "--no-sandbox,--disable-dev-shm-usage,--disable-gpu,"
                "--window-position=0,0,--start-maximized"
            ),
            proxy=PROXY_URL if PROXY_URL else None,
        ) as sb:
            try:
                self.log("✅ 浏览器已启动！")

                # 1. IP
                self.log("🌍 正在检测出口 IP...")
                try:
                    sb.open("https://api.ipify.org?format=json")
                    body_text = sb.get_text("body")
                    ip_val = json.loads(re.search(r"\{.*\}", body_text).group(0)).get(
                        "ip", "Unknown"
                    )
                    parts = ip_val.split(".")
                    if len(parts) >= 4:
                        self.log(
                            f"✅ 当前出口 IP: {parts[0]}.{parts[1]}.***.{parts[-1]}"
                        )
                    else:
                        self.log(f"✅ 当前出口 IP: {ip_val}")
                except Exception:
                    self.log("⚠️ IP 检测跳过...")

                # 2. 注入 Cookie（必须在 dash 域）
                self.inject_cookies(sb)

                # 3. 进 dash 项目页
                self.log("📂 进入 Project 页面并校验登录态")
                self.ensure_logged_in(sb)
                time.sleep(2)
                try:
                    sb.scroll_to_bottom()
                except Exception:
                    pass
                self.close_modal_if_any(sb)
                time.sleep(1)

                # 4. 读过期时间 / Renew
                selector = "button:contains('Renew')"
                self.log("🖱️ 查找 Renew 按钮 / 读取过期时间")
                time_before = self.get_expiry_time(sb)

                if not sb.is_element_visible(selector):
                    self.log("✅ 无发现 Renew 按钮，无需续期")
                    renew_screenshot = os.path.join(self.screenshot_dir, "renew.png")
                    sb.save_screenshot(renew_screenshot)
                    self.send_telegram_notify(
                        f"🎉Aclclouds 自动续期\n🕒当前无需续期\n🚀剩余使用时间：{time_before}",
                        renew_screenshot,
                    )
                    return

                self.log("✅ 找到 Renew 按钮")
                sb.wait_for_element_visible(selector, timeout=10)
                sb.scroll_to(selector)
                time.sleep(5)
                sb.click(selector)

                # 5. Verify
                verify_selector = ".auth-captcha-checkbox"
                self.log("🖱️ 点击验证按钮")
                sb.wait_for_element_visible(verify_selector, timeout=10)
                self.log("✅ 找到 Verify 按钮并点击")
                sb.click(verify_selector)
                time.sleep(5)

                clickverify_screenshot = os.path.join(
                    self.screenshot_dir, "clickverify.png"
                )
                sb.save_screenshot(clickverify_screenshot)
                self.send_telegram_notify("已点击验证按钮", clickverify_screenshot)

                if not sb.is_element_visible("text=Server renewed successfully"):
                    self.log("🔥 开始执行验证码破解")
                    for i in range(20):
                        self.run_crack(sb, i)
                        time.sleep(2)
                        if sb.is_element_visible("text=Server renewed successfully"):
                            self.log("✅ 验证码破解成功")
                            break

                    if not sb.is_element_visible("text=Anti-bot confirmation"):
                        if not sb.is_element_visible(
                            "text=Server renewed successfully"
                        ):
                            time.sleep(90)
                            selector = "button:contains('Renew')"
                            try:
                                sb.wait_for_element_visible(selector, timeout=10)
                                sb.scroll_to(selector)
                                self.log("🖱️ 已等待 1 分半钟并开始点击 Renew 按钮")
                                sb.click(selector)
                                time.sleep(5)
                            except Exception as e:
                                self.log(f"重试点击 Renew 失败: {e}")

                # 6. 再进 dash 项目页
                self.log("📂 再次进入 Project 页面")
                sb.uc_open_with_reconnect(PROJECT_URL, reconnect_time=25)
                time.sleep(5)
                if "dash.aclclouds.com" not in sb.get_current_url():
                    sb.open(PROJECT_URL)
                    time.sleep(3)
                self.close_modal_if_any(sb)
                time_after = self.get_expiry_time(sb)

                verify_screenshot = os.path.join(self.screenshot_dir, "verify.png")
                sb.save_screenshot(verify_screenshot)
                self.send_telegram_notify(
                    f"🎉Aclclouds 自动续期\n"
                    f"🕒续期前剩余使用时间：{time_before}\n"
                    f"🚀续期后剩余使用时间：{time_after}",
                    verify_screenshot,
                )
                self.log("✅ 流程完毕")

            except Exception as e:
                self.log(f"❌ 运行异常: {e}")
                import traceback
                traceback.print_exc()
                photo = None
                try:
                    photo = self.save_debug(sb, "error")
                except Exception:
                    try:
                        err_path = os.path.join(self.screenshot_dir, "error.png")
                        sb.save_screenshot(err_path)
                        photo = err_path
                    except Exception:
                        pass
                self.send_telegram_notify(f"❌ Aclclouds 续期失败\n{e}", photo)


if __name__ == "__main__":
    AclcloudsRenewal().run()
