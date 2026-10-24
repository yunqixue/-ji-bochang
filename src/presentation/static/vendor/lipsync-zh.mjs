/**
 * @class 中文唇形同步处理器（近似方案）
 *
 * TalkingHead 官方（v1.4）没有中文 lipsync 模块，只有 fi/en/lt 等。
 * 本模块用「汉字 → 伪音节」的确定性映射补上这一课：
 *
 *   每个汉字 = 声母视素（闭口类 PP/DD/kk/CH/SS/nn/FF/TH）
 *            + 韵母视素（开口类 aa/E/I/O/U）
 *
 * 时长按 4:9 分配（相对单位）。TalkingHead 会把这里的相对时长
 * 整体缩放到 edge-tts WordBoundary 给出的真实词时长上，
 * 因此口型节奏与真实发音逐词对齐。
 *
 * 注意：这不是音素级精确（没做拼音转换），是视觉近似方案 ——
 * 目标是"说话时嘴在合理地动、节奏对得上"，不是播音员级口型。
 * 要更精确，后续可以接 pinyin 库把汉字转成真实声韵母再映射。
 *
 * 接口与官方模块一致：preProcessText(s) / wordsToVisemes(w)，
 * 导出类名必须是 LipsyncZh（TalkingHead 按 'Lipsync' + 语言码首字母大写 拼类名）。
 */

// 声母（闭口/半闭口动作）与韵母（开口动作）视素池
const INITIALS = ['PP', 'DD', 'kk', 'CH', 'SS', 'nn', 'FF', 'TH'];
const FINALS = ['aa', 'E', 'I', 'O', 'U'];

class LipsyncZh {

  constructor() {}

  /**
   * 预处理：去掉标点和空白，只保留汉字/字母/数字。
   * edge-tts 的 WordBoundary 文本常带尾部标点（"你好，"），
   * 标点不发音，留着会产生多余口型。
   */
  preProcessText(s) {
    return (s || '').replace(/[^一-鿿\w]/g, '');
  }

  /**
   * 词 → 视素序列。返回 { visemes, times, durations }（相对时长单位）。
   * TalkingHead 内部会按真实词时长做整体缩放，这里只管相对比例。
   */
  wordsToVisemes(w) {
    const o = { words: w, visemes: [], times: [], durations: [] };
    let t = 0;

    for (const ch of w) {
      const code = ch.codePointAt(0);
      if (code >= 0x4e00 && code <= 0x9fff) {
        // 汉字 → 声母 + 韵母：用字符编码做确定性哈希，
        // 同一个字永远映射到同一组口型（避免"忽左忽右"的随机感）
        o.visemes.push(INITIALS[code % INITIALS.length]);
        o.times.push(t);
        o.durations.push(4);
        t += 4;
        o.visemes.push(FINALS[(code >> 3) % FINALS.length]);
        o.times.push(t);
        o.durations.push(9);
        t += 9;
      } else if (/\w/.test(ch)) {
        // 字母/数字：单个开口动作带过
        o.visemes.push('aa');
        o.times.push(t);
        o.durations.push(8);
        t += 8;
      } else {
        // 其他符号：短暂闭口
        o.visemes.push('sil');
        o.times.push(t);
        o.durations.push(3);
        t += 3;
      }
    }

    return o;
  }
}

export { LipsyncZh };
