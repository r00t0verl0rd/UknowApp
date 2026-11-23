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
    description: "Получатель пока не подключил Telegram.",
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
    { title: "Telegram · Ученик", description: "Копию в Telegram пока не удалось отправить.", delivered: false },
  ]);
});
test("legacy Telegram logs still work and duplicate modern results are not shown", () => {
  assert.equal(getDeliveryDetails({
    telegram_delivery_errors: [{ name: "Анна", reason: "Аккаунт получателя не подключён к TELEGRAM" }],
  })[0].description, "Получатель пока не подключил Telegram.");
  assert.equal(getDeliveryDetails({
    messenger_deliveries: { telegram: { delivered: [{ user_id: 1 }] } },
    telegram_deliveries: [{ user_id: 1 }],
  }).length, 1);
  assert.deepEqual(getDeliveryDetails({}), []);
});
