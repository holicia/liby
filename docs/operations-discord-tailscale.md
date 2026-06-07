# 외부 분석/열람 운영 가이드 (Discord + Tailscale)

공개 인터넷 노출 없이, 폰에서 분석을 트리거하고 결과를 본다.
집 PC가 켜져 있어야 한다(분석은 로컬 Docker bridge에서만 동작).

## 1. Discord 봇 만들기

1. https://discord.com/developers/applications → New Application.
2. Bot 탭 → Add Bot → **Reset Token** 으로 토큰 복사(`DISCORD_LIBY_TOKEN`).
3. Bot 탭에서 **Message Content Intent** 활성화(필수 — 메시지 본문 수신).
4. OAuth2 → URL Generator → scopes `bot`, 권한 `Send Messages`/`Read Message History`
   선택 → 생성된 URL로 **나만 들어가는 개인 서버**에 봇 초대.
5. 그 서버에 **전용 비공개 채널**을 하나 만든다(나·봇만 접근 가능하게).
   개발자 모드 ON(설정 → 고급) 후 채널 우클릭 "채널 ID 복사"(`DISCORD_LIBY_CHANNEL_ID`).

> 권한은 **채널 기준**이다. 이 채널에 들어온 메시지에만 봇이 반응하므로,
> 채널을 본인만 접근 가능하게 두면 사실상 본인 전용이 된다. 사용자 ID는 필요 없다.
> (`DISCORD_LIBY_APP_ID`·`DISCORD_LIBY_APP_PUBLIC_KEY`는 슬래시 명령/웹훅 방식용이라
> 이 게이트웨이 봇에선 쓰지 않는다 — .env에 남겨둬도 무방.)

## 2. .env 설정

```
DISCORD_LIBY_TOKEN=<봇 토큰>
DISCORD_LIBY_CHANNEL_ID=<전용 비공개 채널 ID>
PUBLIC_BASE_URL=http://<PC-MagicDNS-이름>.ts.net:8000
# 선택: 내부 API 추가 보호
BOT_API_TOKEN=<임의 문자열>
```

`PUBLIC_BASE_URL`은 Tailscale을 켠 뒤 4단계에서 확정한다.

## 3. 서버 실행 (한 번에 전부)

봇은 in-process라 uvicorn 한 번이면 서버 + 워커 + 봇이 함께 뜬다.
타이넷/LAN 기기가 웹 UI에 닿도록 `0.0.0.0`에 바인딩한다(이것만으로는 공개 아님 —
Tailscale/LAN 안에서만 도달).

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

선택: 위 명령을 `start.ps1`로 저장하고 Windows 작업 스케줄러 "로그온 시 실행"에
등록하면 재부팅 후 자동 기동.

## 4. Tailscale (사설망 — 전체 노트 열람용)

1. PC와 폰에 Tailscale 설치, 같은 계정으로 로그인(`tailscale up`).
2. PC의 MagicDNS 이름 확인: `tailscale status` 또는 관리 콘솔.
3. `.env`의 `PUBLIC_BASE_URL`을 `http://<그 이름>:8000`으로 설정하고 서버 재시작.
4. 폰에서 Tailscale ON → 임베드의 "전체 노트" 링크가 read.html로 열린다.

> Tailscale은 **내 기기끼리만** 연결되는 사설 메시 VPN이다. 인터넷에 공개되지 않으며
> 별도 인증 레이어가 필요 없다. Cloudflare 퍼블릭 터널과 다른 점이 이것.

## 5. 사용

- **전용 채널에** 유튜브 링크를 보낸다 → ⏳ → 잠시 후 요약 임베드.
- 임베드 타임라인의 시간 링크를 누르면 폰 유튜브 앱이 해당 지점으로 점프.
- "전체 노트" 링크(Tailscale ON)로 브라우저에서 전체 노트 열람.
- 상세 분석: 메시지를 `상세 <링크>`로 시작.
- 일반 텍스트/메모도 그대로 보내면 text 노트로 분석된다.
- 지정 채널(`DISCORD_LIBY_CHANNEL_ID`) 밖의 메시지는 무시된다.
