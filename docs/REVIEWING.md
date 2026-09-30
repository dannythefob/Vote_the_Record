# Reviewing and verifying facts

Everything the research tools gather starts as **Unverified**. Only the project owner marks
items verified. This page explains how, step by step.

## Start the review page

1. In VS Code, open a terminal: menu **Terminal → New Terminal**.
2. Type this and press Enter:

   ```
   .venv\Scripts\python src\review\review.py
   ```

3. Your browser opens the review page. (If it doesn't, open http://127.0.0.1:8765 yourself.)
4. The first time, type your name in **Your name as reviewer** and click **Save name**. This
   is the name shown publicly next to "Verified". It is saved on your computer only.

## Verify an item

Each card is one fact, or one link between a record and a survey question.

1. Click **Open source ↗** and read the source. Does it say exactly what the card says?
2. Click **Open archived copy ↗**. Does the saved copy show the same thing?
3. If both match, click **✓ Mark verified**, then **OK** in the confirmation box.

The card turns green. Behind the scenes, the page changes only that item's three
verification lines and runs the checker. If the checker objects, the change is undone and
you see why.

For a **question link**, also decide whether you agree with the options it supports and the
"Why" reasoning. Verify it only if you do.

## Verify many at once

Many facts cite the same source. For example, every race on the Harris ballot cites a page of
the County Clerk's sample ballot. To check them together:

1. Tick **Group by source** at the top. Cards are now grouped by the document they cite.
2. Open that source once, and check every card in the group against it.
3. Click **✓ Verify all N ready in this group**. The confirmation box lists every item it
   will change. Click **OK** only if you checked every one.

Only unverified items that are ready (not grey) are changed. The checker runs once for the
whole group; if it objects to anything, nothing is changed. Any single card can still be
undone with **Undo**. Question links are never included; verify those one at a time.

The same button appears on each file's group when **Group by source** is off.

## If something is wrong

Don't verify it. Tell Claude which item (the code after the name, like `B-02`) and what
doesn't match, and it will be corrected or removed.

## Made a mistake?

Click **Undo** on a green card to set it back to Unverified.

## Some buttons are grey

A grey button means the item can't be verified yet, and the card says why (usually that no
archived copy exists). Ask Claude to fix that first.

## When you're done

1. Go back to the terminal and press **Ctrl + C** to stop the review page.
2. Tell Claude "check and commit my verifications". It will check, build, commit, and push.
3. Merge on GitHub as usual. Your verifications go live, with your name and the date.
