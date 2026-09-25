/**
 * Page translators (Google Translate, Yandex Browser's built-in one) swap
 * React-owned text nodes for their own wrappers (<font>, <ya-tr-span>).
 * React still holds the original node, so the next commit that removes it
 * or inserts next to it throws NotFoundError and the root boundary blanks
 * the whole app (facebook/react#11538). HRP-133 keeps the app translatable,
 * so instead of forbidding translation these two DOM calls tolerate a node
 * the translator already moved — the only case in which they would throw:
 * a removal is skipped, an insertion lands at the end of the parent.
 *
 * ponytail: a skipped removal leaves the translator's copy of that text on
 * screen, and an appended node can sit out of order, until the parent
 * remounts; `translate="no"` on the subtree is the upgrade for a surface
 * where that matters (see GenerationDrawer).
 */
export function guardDomAgainstTranslators(): void {
  if (typeof Node !== "function") return;

  const removeChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) {
      console.warn("[translator-dom-guard] removeChild skipped: node moved by a page translator");
      return child;
    }
    return removeChild.call(this, child) as T;
  };

  const insertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function <T extends Node>(
    this: Node,
    node: T,
    child: Node | null,
  ): T {
    if (child && child.parentNode !== this) {
      console.warn("[translator-dom-guard] insertBefore appended: node moved by a page translator");
      return insertBefore.call(this, node, null) as T;
    }
    return insertBefore.call(this, node, child) as T;
  };
}
