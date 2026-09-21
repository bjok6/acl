#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from seleniumbase import SB
from selenium.common.exceptions import ElementClickInterceptedException, WebDriverException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from zoneinfo import ZoneInfo

# ----- 配置（从环境变量读取或在双引号内填写） -----
EMAIL = os.getenv('EMAIL') or ""
PASSWORD = os.getenv('PASSWORD') or ""
TG_CHAT_ID = os.getenv('TG_CHAT_ID') or ""
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN') or ""

LOGIN_PATH = '/auth/login'
BASE_URL = 'https://aclclouds.com'
PROJECTS_URL = f'{BASE_URL}/dashboard/projects'

def beijing_time_str():
    try:
        return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')

def send_telegram(message):
    if TG_BOT_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        data = {'chat_id': TG_CHAT_ID, 'text': message}
        try:
            requests.post(url, data=data, timeout=10)
            print(f"Telegram sent: {message[:50]}...")
        except Exception as e:
            print(f"Failed to send Telegram: {e}")
    else:
        print(f"[Telegram disabled] {message}")

def wait_for_url_change(sb, original_url, timeout=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        current_url = sb.get_current_url()
        if current_url != original_url:
            return True
        sb.sleep(0.5)
    raise Exception(f"等待 URL 变化超时 ({timeout}秒)，当前仍为: {original_url}")

def is_login_page(sb):
    return LOGIN_PATH in sb.get_current_url()

def is_logged_in(sb):
    current_url = sb.get_current_url()
    return BASE_URL in current_url and LOGIN_PATH not in current_url

def scroll_to_selector(sb, selector):
    sb.scroll_to(selector)
    sb.sleep(0.2)

def safe_click_element(sb, element, label):
    try:
        sb.driver.execute_script(
            'arguments[0].scrollIntoView({block: "center", inline: "center"});',
            element,
        )
        sb.sleep(0.5)

        try:
            element.click()
            return True
        except (ElementClickInterceptedException, WebDriverException, StaleElementReferenceException) as e:
            print(f"{label} 普通点击失败，改用 JavaScript 点击: {e}")

        sb.driver.execute_script('arguments[0].click();', element)
        sb.sleep(0.5)
        return True
    except StaleElementReferenceException:
        print(f"{label} 元素已失效，点击前需要重新定位")
        return False

def element_text(element):
    try:
        return element.text.strip()
    except Exception:
        return ''

def unique_elements(elements):
    unique = []
    seen = set()
    for element in elements:
        element_id = getattr(element, 'id', None)
        if element_id and element_id in seen:
            continue
        if element_id:
            seen.add(element_id)
        unique.append(element)
    return unique

def click_captcha_checkbox(sb, label='验证码', timeout=10):
    selectors = [
        'div.auth-captcha-inner[role="checkbox"]',
        '//div[contains(., "Anti-bot confirmation")]//*[@role="checkbox"]',
        '//div[contains(., "I am not a robot")]//*[@role="checkbox"]',
        '//div[contains(@class, "modal") and contains(., "Secured by ACLClouds")]//*[@role="checkbox"]',
    ]

    last_error = None
    clicked = False
    selector = None
    for candidate in selectors:
        try:
            sb.wait_for_element_visible(candidate, timeout=timeout)
            scroll_to_selector(sb, candidate)
            sb.uc_click(candidate)
            sb.sleep(1)
            selector = candidate
            clicked = True
            break
        except Exception as e:
            last_error = e
            continue

    if not clicked:
        print(f"{label} 点击复选框失败: {last_error}")
        return False

    sb.sleep(3)
    captcha_ok = handle_captcha_challenge(sb, label, timeout=20)
    if not captcha_ok:
        print(f"{label} 验证流程未完成，等待状态仍未确认。")
        return False

    try:
        checked = sb.get_attribute(selector, 'aria-checked')
        if checked == 'true':
            print(f"{label} 验证通过")
            return True
        else:
            print(f"{label} 验证未完成，当前状态: {checked}")
            return False
    except Exception:
        return True

def handle_captcha_challenge(sb, label='验证码', timeout=20):
    start_time = time.time()
    challenge = None
    challenge_selectors = [
        '.auth-captcha-challenge',
        '.auth-capcha-challenge',
        '//*[contains(@class, "captcha") and contains(@class, "challenge")]',
        '//*[contains(@aria-label, "Click on ") or contains(@aria-label, "Select ") or contains(@class, "challenge")]',
    ]

    def get_challenge():
        for selector in challenge_selectors:
            try:
                if selector.startswith('/'):
                    elems = sb.driver.find_elements(By.XPATH, selector)
                    for elem in elems:
                        if elem.is_displayed():
                            return elem
                else:
                    elem = sb.wait_for_element_visible(selector, timeout=1)
                    if elem and elem.is_displayed():
                        return elem
            except Exception:
                continue
        return None

    while time.time() - start_time < timeout:
        challenge = get_challenge()
        if challenge:
            print(f"{label} 检测到图形验证码挑战")
            break
        try:
            checkbox = sb.driver.find_element(By.CSS_SELECTOR, 'div.auth-captcha-inner[role="checkbox"]')
            if checkbox.get_attribute('aria-checked') == 'true':
                print(f"{label} 验证复选框已勾选，验证码流程已完成")
                return True
        except Exception:
            pass
        sb.sleep(0.3)

    if not challenge:
        return True

    target = ''
    try:
        prompt = challenge.find_element(By.CSS_SELECTOR, '.auth-captcha-prompt strong, .auth-capcha-prompt strong')
        target = prompt.text.strip()
    except Exception:
        pass

    if not target:
        aria_label = challenge.get_attribute('aria-label') or ''
        if 'Click on ' in aria_label:
            target = aria_label.split('Click on ')[-1].strip()

    print(f"{label} 目标文本: {target or '未识别'}")

    option_selectors = [
        '.auth-captcha-option',
        '.auth-capcha-option',
        './/button',
        './/a',
        './/div[@role="button"]',
    ]

    def get_options(challenge_elem):
        for sel in option_selectors:
            try:
                if sel.startswith('.') or sel.startswith('['):
                    elems = challenge_elem.find_elements(By.CSS_SELECTOR, sel)
                else:
                    elems = challenge_elem.find_elements(By.XPATH, sel)
                if elems:
                    return [elem for elem in elems if elem.is_displayed() and elem.is_enabled()]
            except Exception:
                continue
        return []

    attempts = 0
    max_attempts = 8
    while attempts < max_attempts:
        challenge = get_challenge()
        if not challenge:
            print(f"{label} 挑战窗口已消失，验证完成")
            return True

        options = get_options(challenge)
        if not options:
            print(f"{label} 当前挑战没有可点击选项，重试中...")
            attempts += 1
            sb.sleep(0.8)
            continue

        candidate = None
        if target:
            for opt in options:
                opt_info = (opt.text or '').strip()
                try:
                    img = opt.find_element(By.TAG_NAME, 'img')
                    opt_info += " " + (img.get_attribute('alt') or '') + " " + (img.get_attribute('src') or '') + " " + (img.get_attribute('title') or '')
                except Exception:
                    pass
                try:
                    opt_info += " " + (opt.get_attribute('aria-label') or '') + " " + (opt.get_attribute('title') or '')
                except Exception:
                    pass

                if target.lower() in opt_info.lower():
                    candidate = opt
                    print(f"{label} 精准匹配到目标 '{target}' 的选项！")
                    break

        if candidate is None:
            chosen_idx = attempts % len(options)
            candidate = options[chosen_idx]
            print(f"{label} 未能精准匹配，轮流测试第 {chosen_idx + 1}/{len(options)} 个选项 ...")

        clicked = safe_click_element(sb, candidate, f"{label} 选项候选")
        if not clicked:
            attempts += 1
            sb.sleep(0.8)
            continue

        sb.sleep(3)

        try:
            checkbox = sb.driver.find_element(By.CSS_SELECTOR, 'div.auth-captcha-inner[role="checkbox"]')
            if checkbox.get_attribute('aria-checked') == 'true':
                print(f"{label} 验证复选框已勾选，验证码流程已完成")
                return True
        except Exception:
            pass

        if not get_challenge():
            print(f"{label} 挑战已消失，验证完成")
            return True

        attempts += 1

    print(f"{label} 多次尝试后仍未完成验证码")
    return False

def mask_email(email):
    if not email or '@' not in email:
        return email or ''

    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + '****' if local else '****'
    elif len(local) <= 4:
        masked_local = f"{local[0]}****{local[-1]}"
    else:
        masked_local = f"{local[:2]}****{local[-2:]}"
    return f"{masked_local}@{domain}"

def build_success_message(server_name, old_status, new_status):
    masked_email = mask_email(EMAIL)
    lines = [
        "🇫🇷 Aclclouds 续期通知",
        "",
        f"✅ 续期/恢复成功: {server_name}",
        f"⏱️ 旧状态: {old_status}",
        f"⏱️ 新状态: {new_status}",
        f"👤 登录账户: {masked_email}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]
    return "\n".join(lines)

def build_not_yet_due_message(server_name, status):
    masked_email = mask_email(EMAIL)
    lines = [
        "🇫🇷 Aclclouds 续期通知",
        "",
        f"⏳ 未到续期时间: {server_name}",
        f"⏱️ 当前状态/剩余: {status}",
        f"👤 登录账户: {masked_email}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]
    return "\n".join(lines)

def handle_renew_antibot(sb, server_name):
    modal_selectors = [
        '//div[contains(., "Anti-bot confirmation")]',
        '//div[contains(., "Confirm you are human")]',
        '//div[contains(., "I am not a robot")]',
    ]

    for selector in modal_selectors:
        try:
            sb.wait_for_element_visible(selector, timeout=5)
            print(f"[{server_name}] 检测到人机验证窗口")
            return click_captcha_checkbox(sb, '续期/激活人机验证', timeout=5)
        except Exception:
            continue

    print(f"[{server_name}] 未检测到人机验证窗口，继续下一步")
    return False

def js_set_input_value(sb, selector, value):
    sb.execute_script(
        '''
        const el = document.querySelector(arguments[0]);
        if (!el) return false;
        el.focus();
        el.value = arguments[1];
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        return true;
        ''',
        selector,
        value,
    )

def fill_input(sb, selector, value, label, timeout=15):
    sb.wait_for_element_visible(selector, timeout=timeout)
    scroll_to_selector(sb, selector)
    sb.click(selector)
    sb.clear(selector)
    sb.type(selector, value)

    entered_value = sb.get_value(selector)
    if label == '密码':
        print(f"{label}输入框当前值长度: {len(entered_value)}")
    else:
        print(f"{label}输入框当前值: '{entered_value}'")

    if entered_value != value:
        print(f"{label}输入未生效，使用 JavaScript 强制赋值并触发事件")
        js_set_input_value(sb, selector, value)
        entered_value = sb.get_value(selector)

    return entered_value == value

def login(sb, email, password):
    print("开始登录流程...")
    if not fill_input(sb, '#username', email, '邮箱'):
        print("⚠️ 邮箱仍未能正确填入")

    if not fill_input(sb, '#password', password, '密码'):
        print("⚠️ 密码仍未能正确填入")

    captcha_ok = click_captcha_checkbox(sb, '登录验证码')
    if not captcha_ok:
        print("⚠️ 登录验证码未完成，暂不点击登录按钮")
        return False

    sb.sleep(1)

    login_page_url = sb.get_current_url()
    clicked = False

    for selector in ['button[type="submit"]', 'div.auth-submit-btn',
                     '//button[contains(text(), "Sign in")]',
                     '//div[contains(text(), "Sign in")]']:
        try:
            sb.wait_for_element_visible(selector, timeout=5)
            scroll_to_selector(sb, selector)
            sb.click(selector)
            clicked = True
            print(f"点击 Sign in 使用: {selector}")
            break
        except Exception as e:
            print(f"选择器 {selector} 失败: {e}")

    if not clicked:
        sb.execute_script('''
            var els = document.querySelectorAll('div, button, a');
            for (var el of els) {
                if (el.textContent.trim() === 'Sign in') {
                    el.click();
                    return true;
                }
            }
            return false;
        ''')

    try:
        wait_for_url_change(sb, login_page_url, timeout=30)
        if '/auth/login' not in sb.get_current_url():
            print("✅ 登录成功！")
            return True
        else:
            print("❌ 登录失败")
            return False
    except Exception as e:
        print(f"登录过程异常: {e}")
        return False

def get_current_ip(proxy_server: str = "") -> str:
    proxies = None
    if proxy_server:
        proxies = {"http": proxy_server, "https": proxy_server}
    response = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
    response.raise_for_status()
    return response.text.strip()

def process_server_page(sb, server_url):
    """进入单个服务器详情页处理续期或重新激活"""
    print(f"\n正在访问服务器详情页: {server_url}")
    sb.open(server_url)
    sb.wait_for_ready_state_complete()
    sb.sleep(2)

    # 1. 获取服务器名称 (如 okdan)
    server_name = "未知服务器"
    try:
        for selector in ['h1', 'h2', 'div[class*="title"]']:
            elems = sb.driver.find_elements(By.CSS_SELECTOR, selector)
            for elem in elems:
                text = element_text(elem)
                if text and len(text) < 40 and text.lower() not in ['console', 'version', 'files', 'aclclouds']:
                    server_name = text
                    break
            if server_name != "未知服务器":
                break
    except Exception:
        pass

    # 2. 获取剩余时间或停机状态
    status_text = "未知"
    try:
        page_text = sb.driver.find_element(By.TAG_NAME, 'body').text
        if "Suspended" in page_text or "suspendu" in page_text.lower():
            status_text = "已暂停 (Suspended)"
        else:
            match = re.search(r'Time remaining:\s*([^\n]+)', page_text, re.I)
            if match:
                status_text = match.group(1).strip()
            else:
                match_alt = re.search(r'(\d+\s*d\s*\d+\s*h|\d+\s*h|\d+\s*d)', page_text, re.I)
                if match_alt:
                    status_text = match_alt.group(0).strip()
    except Exception:
        pass

    print(f"[{server_name}] 当前状态: {status_text}")

    # 3. 兼容匹配 Renew (续期) 和 Reactivate (重新激活) 按钮
    action_btns = []
    action_selectors = [
        '//button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "renew")]',
        '//button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "reactivate")]',
        'button[class*="renew"]',
        'button[class*="reactivate"]',
        '.projects-renew-btn'
    ]
    for selector in action_selectors:
        try:
            if selector.startswith('//'):
                elems = sb.driver.find_elements(By.XPATH, selector)
            else:
                elems = sb.driver.find_elements(By.CSS_SELECTOR, selector)
            action_btns.extend([e for e in elems if e.is_displayed()])
        except Exception:
            continue

    action_btns = unique_elements(action_btns)

    # 4. 执行点击与人机验证
    if action_btns:
        btn_label = element_text(action_btns[0]) or "Renew/Reactivate"
        print(f"[{server_name}] 发现操作按钮 [{btn_label}]，开始点击...")
        safe_click_element(sb, action_btns[0], f"[{server_name}] {btn_label} 按钮")
        handle_renew_antibot(sb, server_name)

        print(f"[{server_name}] 正在刷新页面确认结果...")
        sb.sleep(3)
        sb.refresh()
        sb.wait_for_ready_state_complete()
        sb.sleep(2)

        # 重新获取刷新后的状态
        new_status_text = "未知"
        try:
            new_page_text = sb.driver.find_element(By.TAG_NAME, 'body').text
            match = re.search(r'Time remaining:\s*([^\n]+)', new_page_text, re.I)
            if match:
                new_status_text = match.group(1).strip()
            elif "Suspended" not in new_page_text and "suspendu" not in new_page_text.lower():
                new_status_text = "已重新激活上线 (Online)"
        except Exception:
            pass

        print(f"[{server_name}] 处理完成！旧状态: {status_text} -> 新状态: {new_status_text}")
        send_telegram(build_success_message(server_name, status_text, new_status_text))
    else:
        print(f"[{server_name}] 当前未显示 Renew 或 Reactivate 按钮")
        send_telegram(build_not_yet_due_message(server_name, status_text))

def main():
    IS_PROXY = os.environ.get("IS_PROXY", "false").lower() == "true"
    PROXY_SERVER = os.getenv('S5_PROXY') or os.getenv('PROXY_SERVER') or "socks://127.0.0.1:1080"

    sb_options = {'uc': True, 'headless': False}
    if IS_PROXY:
        sb_options['proxy'] = PROXY_SERVER
        print(f"🔗 挂载代理: {PROXY_SERVER}")
    else:
        print("🍭 未使用代理，直连访问")

    with SB(**sb_options) as sb:
        try:
            ip = get_current_ip(PROXY_SERVER if IS_PROXY else "")
            print(f"📍 当前出口IP: {ip}")
        except Exception as e:
            print(f"获取出口IP失败: {e}")

        sb.set_window_size(1366, 768)

        if not is_login_page(sb):
            sb.open(BASE_URL)
            sb.wait_for_ready_state_complete()
            time.sleep(2)

        if is_login_page(sb):
            if not EMAIL or not PASSWORD:
                print("❌ 未配置 EMAIL 或 PASSWORD，无法执行登录。")
                send_telegram("⚠️ 未配置 EMAIL 或 PASSWORD。")
                return
            if not login(sb, EMAIL, PASSWORD):
                return
        elif is_logged_in(sb):
            print(f"✅ 当前已登录。URL: {sb.get_current_url()}")
        else:
            print(f"❌ 未能确认登录状态。")
            send_telegram("⚠️ 未能确认登录状态。")
            return

        # 访问项目列表页提取所有服务器链接 (/server/xxx)
        sb.open(PROJECTS_URL)
        sb.wait_for_ready_state_complete()
        time.sleep(3)

        server_urls = []
        try:
            links = sb.driver.find_elements(By.XPATH, '//a[contains(@href, "/server/")]')
            for link in links:
                href = link.get_attribute('href')
                if href and href not in server_urls:
                    server_urls.append(href)
        except Exception as e:
            print(f"提取服务器链接失败: {e}")

        if not server_urls:
            print("❌ 未找到任何服务器详情页链接，请检查页面结构。")
            send_telegram("⚠️ 未找到服务器链接，请检查脚本。")
            return

        print(f"共检测到 {len(server_urls)} 个服务器，开始依次处理...")
        for server_url in server_urls:
            try:
                process_server_page(sb, server_url)
            except Exception as e:
                print(f"处理服务器 {server_url} 时出错: {e}")
                send_telegram(f"🇫🇷 Aclclouds 续期通知\n\n⚠️ 处理出错: {str(e)}")

        print("所有服务器处理完成。")

if __name__ == '__main__':
    main()
