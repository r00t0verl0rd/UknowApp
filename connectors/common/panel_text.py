def teacher_panel_text(chat, visible, page, total):
    if chat:
        lines = ["🔸 " + chat["name"]]
        if chat["total"] > len(chat["messages"]):
            lines.append(f'Показаны последние {len(chat["messages"])} из {chat["total"]} сообщений.')
        lines.extend(m["name"] + ": " + m["preview"] for m in chat["messages"])
        if not chat["messages"]:
            lines.append("История пока пуста.")
    else:
        lines = ["▫️ Ваша группа:", ""]
        for item in visible:
            lines.append("🔸 " + item["name"] + (f' · {item["unread"]} новых' if item["unread"] else ""))
            previews = item.get("unread_previews") or []
            lines.extend("   " + p for p in previews or [item["last_message"]])
            if item["unread"] > len(previews) and previews:
                lines.append(f'   …ещё {item["unread"] - len(previews)} сообщений')
            lines.append("")
        if not visible:
            lines.append("Пока нет назначенных учеников.")
        if total > 1:
            lines.append(f"Страница {page+1} из {total}.")
    return "\n".join(lines).rstrip()
