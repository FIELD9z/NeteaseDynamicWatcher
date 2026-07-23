(() => {
  "use strict";

  const snapshots = window.__NETEASE_INTERACTIONS__ || {};

  function text(value) {
    return String(value == null ? "" : value);
  }

  function initial(value) {
    const name = text(value).trim();
    return name ? Array.from(name)[0] : "?";
  }

  function profileHref(value) {
    const raw = text(value).trim();
    if (!raw) return "";
    try {
      const url = new URL(raw);
      if (url.protocol !== "https:" || url.hostname !== "music.163.com") return "";
      return url.href;
    } catch (_) {
      return "";
    }
  }

  function formatTime(comment) {
    if (comment.time_text) return text(comment.time_text);
    const milliseconds = Number(comment.time_ms || 0);
    if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "未知时间";
    return new Date(milliseconds).toLocaleString("zh-CN", { hour12: false });
  }

  function makeUser(user, className) {
    const value = user && typeof user === "object" ? user : {};
    const wrapper = document.createElement("div");
    wrapper.className = className || "interaction-user";

    const avatar = document.createElement("span");
    avatar.className = "interaction-avatar";
    avatar.textContent = initial(value.nickname);
    wrapper.appendChild(avatar);

    const href = profileHref(value.profile_url);
    const name = document.createElement(href ? "a" : "span");
    name.className = "interaction-name";
    name.textContent = text(value.nickname || "未知用户");
    if (href) {
      name.href = href;
      name.target = "_blank";
      name.rel = "noreferrer";
      name.title = "打开网易云个人主页";
    }
    wrapper.appendChild(name);
    return wrapper;
  }

  function makeComment(comment) {
    const item = document.createElement("article");
    item.className = "interaction-comment";

    const header = document.createElement("header");
    header.appendChild(makeUser(comment.user));

    const meta = document.createElement("span");
    meta.className = "interaction-meta";
    const parts = [formatTime(comment)];
    if (comment.hot) parts.push("热门评论");
    const likes = Number(comment.liked_count || 0);
    if (likes > 0) parts.push(`获赞 ${likes}`);
    meta.textContent = parts.join(" · ");
    header.appendChild(meta);
    item.appendChild(header);

    const body = document.createElement("p");
    body.textContent = text(comment.content || "（评论内容为空）");
    item.appendChild(body);

    const replies = Array.isArray(comment.replies) ? comment.replies : [];
    if (replies.length) {
      const replyList = document.createElement("div");
      replyList.className = "interaction-replies";
      replies.forEach((reply) => {
        const row = document.createElement("div");
        row.className = "interaction-reply";
        row.appendChild(makeUser(reply.user, "interaction-user interaction-user-small"));
        const content = document.createElement("span");
        content.textContent = text(reply.content || "（回复内容为空）");
        row.appendChild(content);
        replyList.appendChild(row);
      });
      item.appendChild(replyList);
    }
    return item;
  }

  function statusMessage(state, kind, savedCount, total) {
    const status = text(state[`${kind}_status`] || "pending");
    if (status === "failed") return "最近一次获取失败，已保留原有数据并等待退避重试。";
    if (status === "unsupported") {
      return kind === "likers"
        ? "当前未配置稳定的点赞用户接口，仅保留点赞人数。"
        : "当前接口不支持获取详情。";
    }
    if (status === "unavailable") return "这条动态没有可用的评论线程标识。";
    if (status === "pending" && savedCount === 0) return "尚未轮到这条动态刷新互动详情。";
    if (total > savedCount) return `已归档 ${savedCount} 条，网易云显示总数 ${total}。`;
    return "";
  }

  function makeCommentsDetails(snapshot) {
    const comments = Array.isArray(snapshot.comments) ? snapshot.comments : [];
    const state = snapshot.state && typeof snapshot.state === "object" ? snapshot.state : {};
    const total = Math.max(Number(state.comment_total || 0), comments.length);
    const details = document.createElement("details");
    details.className = "interaction-details";
    const summary = document.createElement("summary");
    summary.textContent = `评论详情 ${total}`;
    details.appendChild(summary);

    const panel = document.createElement("div");
    panel.className = "interaction-panel";
    const note = statusMessage(state, "comments", comments.length, total);
    if (note) {
      const message = document.createElement("p");
      message.className = "interaction-note";
      message.textContent = note;
      panel.appendChild(message);
    }
    if (comments.length) {
      comments.forEach((comment) => panel.appendChild(makeComment(comment)));
    } else {
      const empty = document.createElement("p");
      empty.className = "interaction-empty";
      empty.textContent = total > 0 ? "暂未取得评论正文。" : "暂无已归档评论。";
      panel.appendChild(empty);
    }
    details.appendChild(panel);
    return details;
  }

  function makeLikersDetails(snapshot) {
    const likers = Array.isArray(snapshot.likers) ? snapshot.likers : [];
    const state = snapshot.state && typeof snapshot.state === "object" ? snapshot.state : {};
    const total = Math.max(Number(state.liker_total || 0), likers.length);
    const details = document.createElement("details");
    details.className = "interaction-details";
    const summary = document.createElement("summary");
    summary.textContent = `点赞用户 ${total}`;
    details.appendChild(summary);

    const panel = document.createElement("div");
    panel.className = "interaction-panel";
    const note = statusMessage(state, "likers", likers.length, total);
    if (note) {
      const message = document.createElement("p");
      message.className = "interaction-note";
      message.textContent = note;
      panel.appendChild(message);
    }
    if (likers.length) {
      const grid = document.createElement("div");
      grid.className = "interaction-liker-grid";
      likers.forEach((user) => grid.appendChild(makeUser(user, "interaction-user interaction-liker")));
      panel.appendChild(grid);
    } else {
      const empty = document.createElement("p");
      empty.className = "interaction-empty";
      empty.textContent = total > 0 ? "暂未取得点赞用户列表。" : "暂无已归档点赞用户。";
      panel.appendChild(empty);
    }
    details.appendChild(panel);
    return details;
  }

  function cardEventId(card) {
    const firstCode = card.querySelector(".detail-grid code");
    return firstCode ? text(firstCode.textContent).trim() : "";
  }

  document.querySelectorAll(".event-card").forEach((card) => {
    const eventId = cardEventId(card);
    const snapshot = snapshots[eventId];
    if (!snapshot || typeof snapshot !== "object") return;

    const section = document.createElement("section");
    section.className = "interaction-section";
    section.appendChild(makeCommentsDetails(snapshot));
    section.appendChild(makeLikersDetails(snapshot));

    const footer = card.querySelector(".event-footer");
    if (footer && footer.parentNode) footer.parentNode.insertBefore(section, footer);
  });
})();
