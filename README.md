# NeteaseDynamicWatcher

用于监控指定网易云音乐用户动态的本地程序。

## 当前功能

- 监控指定用户动态
- 识别歌曲分享动态
- 首次运行只保存当前状态，不发送历史通知
- 后续新动态通过 PushMe 通知
- SQLite 本地去重
- 支持 Windows 长时间运行

## 安全说明

- Cookie、通知密钥只保存在本地配置或环境变量。
- 不提交真实账号信息。
- 离线测试使用模拟响应。

## 本地使用流程

1. 复制 `.env.example` 为 `.env`。
2. 填入自己的网易云 Cookie 和 PushMe key。
3. 首次运行：

```text
python run_watcher.py --once
```

首次运行只建立基线。

4. 后续长期运行：

```text
python run_watcher.py
```

默认每 15 分钟检查一次。

## 手动验证

建议先使用 PushMe 自己的测试功能确认手机通知链路正常，再运行监控程序。

## 注意

网易云页面需要登录才能访问动态内容，因此 Cookie 失效后需要更新本地配置。
