undefined
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
