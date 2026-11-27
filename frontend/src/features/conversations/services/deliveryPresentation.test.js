import assert from "node:assert/strict";
import test from "node:test";
import { getDeliveryDetails } from "./deliveryPresentation.js";

test("plain Russian description for unlinked Telegram recipient", () => {
  const details = getDeliveryDetails({
    messenger_deliveries: { telegram: {
      status: "not_connected", delivered: [],
      errors: [{ name: "Профессор", role: "teacher", reason: "Аккаунт получателя не подключён к TELEGRAM" }],
    } },
  });
  assert.deepEqual(details, [{
    title: "Telegram · Профессор",
    description: "Получатель не подключил телеграм-бота.",
    delivered: false,
  }]);
});
test("partial delivery leads with successful copies, never raw error codes", () => {
  assert.deepEqual(getDeliveryDetails({
    messenger_deliveries: {
      telegram: { delivered: [{ user_id: 1 }], errors: [{ role: "student", reason: "ошибка TELEGRAM (TelegramForbiddenError)" }] },
    },
  }), [
    { title: "Telegram", description: "Копия отправлена.", delivered: true },
    { title: "Telegram · Ученик", description: "Telegram пока не подключен.", delivered: false },
  ]);
});
test("legacy Telegram logs still work and duplicate modern results are not shown", () => {
  assert.equal(getDeliveryDetails({
    telegram_delivery_errors: [{ name: "Анна", reason: "Аккаунт получателя не подключён к TELEGRAM" }],
  })[0].description, "Получатель не подключил телеграм-бота.");
  assert.equal(getDeliveryDetails({
    messenger_deliveries: { telegram: { delivered: [{ user_id: 1 }] } },
    telegram_deliveries: [{ user_id: 1 }],
  }).length, 1);
  assert.deepEqual(getDeliveryDetails({}), []);
});

test("successful messenger copy identifies teacher or student by name", () => {
  assert.deepEqual(getDeliveryDetails({
    messenger_deliveries: { telegram: {
      delivered: [{ user_id: 14, name: "Профессор", role: "teacher" }],
      errors: [{ user_id: 22, name: "Падаван", role: "student", reason: "not_connected" }],
    } },
  }, true), [
    { title: "Telegram · Профессор", namedRecipient: "Профессор", role: "teacher", channel: "Telegram",
      description: "Копия отправлена.", delivered: true },
    { title: "Telegram · Падаван", namedRecipient: "Падаван", role: "student", channel: "Telegram",
      description: "Получатель не подключил телеграм-бота.", delivered: false },
  ]);
});

test("historical delivery IDs resolve to actual participants and never falsely credit another", () => {
  const participants = [
    { id: 14, full_name: "Профессор", role: "teacher" },
    { id: 22, full_name: "Падаван", role: "student" },
  ];
  const metadata = {
    messenger_deliveries: { telegram: { delivered: [{ user_id: 14 }] } },
  };
  assert.equal(getDeliveryDetails(metadata, true, participants)[0].title, "Telegram · Профессор");
  assert.equal(getDeliveryDetails(metadata, true, participants)[0].role, "teacher");
  assert.equal(getDeliveryDetails(metadata, true, [participants[1]])[0].title, "Telegram · Получатель");
  assert.equal(getDeliveryDetails({ telegram_deliveries: [{ user_id: 22 }] }, true, participants)[0].title,
    "Telegram · Падаван");
  const multiple = getDeliveryDetails({
    messenger_deliveries: { telegram: { delivered: [{ user_id: 14 }, { user_id: 22 }] } },
  }, true, participants);
  assert.deepEqual(multiple.map(item => item.title), ["Telegram · Профессор", "Telegram · Падаван"]);
});

test("MAX deliveries are shown by name with their own status", () => {
  assert.deepEqual(getDeliveryDetails({
    messenger_deliveries: {
      max: {
        delivered: [{ user_id: 14, name: "Профессор", role: "teacher" }],
        errors: [{ user_id: 22, name: "Падаван", role: "student", reason: "not_connected" }],
      },
    },
  }, true), [
    {
      title: "MAX · Профессор",
      namedRecipient: "Профессор",
      role: "teacher",
      channel: "MAX",
      description: "Копия отправлена.",
      delivered: true,
    },
    {
      title: "MAX · Падаван",
      namedRecipient: "Падаван",
      role: "student",
      channel: "MAX",
      description: "Получатель пока не подключил MAX.",
      delivered: false,
    },
  ]);
});
