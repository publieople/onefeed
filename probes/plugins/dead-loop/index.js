module.exports = {
  async pull(ctx) {
    while (true) {}   // 永不返回，宿主应在 30s 时强杀
  },
};
