import numpy as np
import graphviz
import os
from sklearn.tree import DecisionTreeClassifier, export_graphviz, _tree, \
    plot_tree

from data_loaders import get_mnist_dataLoader
from utils.tree_utils import get_light_colors

class DecisionPath:
    def __init__(self, node_indices, feature_indices, node_indptr, feature_indptr):
        self.node_indices = node_indices
        self.feature_indices = feature_indices
        self.node_indptr = node_indptr
        self.feature_indptr = feature_indptr

class CustomDecisionTree:
    def __init__(self, n_classes, min_samples_split=2, min_samples_leaf=1, max_depth=1000):
        self.min_samples_split = min_samples_split
        self.min_samples_leaf = min_samples_leaf
        self.max_depth = max_depth
        self.tree = None
        self.node_count = 0
        self.n_classes = n_classes

    class Node:
        def __init__(self, gini, num_samples, num_samples_per_class, predicted_class, node_id,
                     threshold=0, feature_index=0, left=None, right=None):
            self.gini = gini
            self.num_samples = num_samples
            self.num_samples_per_class = num_samples_per_class
            self.predicted_class = predicted_class
            self.feature_index = feature_index
            self.threshold = threshold
            self.left = left
            self.right = right
            self.id = node_id

    def fit(self, X, y):
        self.n_classes = self.n_classes if self.n_classes else len(set(y))
        self.node_count = 0
        self.tree = self._grow_tree(X, y)

    def predict(self, X):
        return [self._predict(inputs) for inputs in X]

    def _grow_tree(self, X, y, depth=0):
        node_id = self.node_count
        num_samples_per_class = [np.sum(y == i) for i in range(self.n_classes)]
        predicted_class = np.argmax(num_samples_per_class)
        node = self.Node(
            gini=self._gini(y),
            num_samples=len(y),
            num_samples_per_class=num_samples_per_class,
            predicted_class=predicted_class,
            node_id=node_id
        )
        self.node_count += 1

        if depth < self.max_depth and len(y) >= self.min_samples_split and len(np.unique(y)) > 1:
            idx, thr = self._best_split(X, y)
            if idx is not None:
                indices_left = X[:, idx] < thr
                X_left, y_left = X[indices_left], y[indices_left]
                X_right, y_right = X[~indices_left], y[~indices_left]
                if len(y_left) >= self.min_samples_leaf and len(y_right) >= self.min_samples_leaf:
                    node.feature_index = idx
                    node.threshold = thr
                    node.left = self._grow_tree(X_left, y_left, depth + 1)
                    node.right = self._grow_tree(X_right, y_right, depth + 1)
                    if self._can_prune(node):
                        if self._investigate_splits(X_left, y_left) and self._investigate_splits(X_right, y_right):
                            node.left = None
                            node.right = None
                            self.node_count = self.node_count - 2
        return node

    def _can_prune(self, node):
        if node.left is None or node.right is None:
            return False
        if node.left.predicted_class == node.right.predicted_class:
            return True
        return False

    def _investigate_splits(self, X, y):
        depth = 0
        while len(y) >= self.min_samples_leaf and depth < self.max_depth:
            idx, thr = self._best_split(X, y)
            if idx is None:
                break
            indices_left = X[:, idx] < thr
            X_left, y_left = X[indices_left], y[indices_left]
            X_right, y_right = X[~indices_left], y[~indices_left]
            if len(y_left) < self.min_samples_leaf or len(y_right) < self.min_samples_leaf:
                break
            predicted_class_left = np.argmax([np.sum(y_left == i) for i in range(self.n_classes)])
            predicted_class_right = np.argmax([np.sum(y_right == i) for i in range(self.n_classes)])
            if predicted_class_left != predicted_class_right:
                return False
            X, y = X_left, y_left
            depth += 1
        return True

    def _best_split(self, X, y):
        m, n = X.shape
        if m <= 1:
            return None, None

        num_parent = [np.sum(y == c) for c in range(self.n_classes)]
        best_gini = 1.0 - sum((num / m) ** 2 for num in num_parent)
        best_idx, best_thr = None, None

        for idx in range(n):
            thresholds, classes = zip(*sorted(zip(X[:, idx], y)))
            num_left = [0] * self.n_classes
            num_right = num_parent.copy()
            for i in range(1, m):
                c = classes[i - 1]
                num_left[c] += 1
                num_right[c] -= 1
                gini_left = 1.0 - sum((num_left[x] / i) ** 2 for x in range(self.n_classes))
                gini_right = 1.0 - sum((num_right[x] / (m - i)) ** 2 for x in range(self.n_classes))
                gini = (i * gini_left + (m - i) * gini_right) / m
                if thresholds[i] == thresholds[i - 1]:
                    continue
                if gini < best_gini:
                    best_gini = gini
                    best_idx = idx
                    best_thr = (thresholds[i] + thresholds[i - 1]) / 2
        return best_idx, best_thr

    def _gini(self, y):
        m = len(y)
        return 1.0 - sum((np.sum(y == c) / m) ** 2 for c in range(self.n_classes))

    def _predict(self, inputs):
        node = self.tree
        while node.left:
            if inputs[node.feature_index] < node.threshold:
                node = node.left
            else:
                node = node.right
        return node.predicted_class

    def apply(self, X):
        return [self._apply(inputs) for inputs in X]

    def _apply(self, inputs):
        node = self.tree
        while node.left:
            if inputs[node.feature_index] < node.threshold:
                node = node.left
            else:
                node = node.right
        return node.id

    def decision_path(self, X):
        """Return the decision path in a format similar to scikit-learn"""
        n_samples = X.shape[0]
        n_nodes = self.node_count

        # Initialize the attributes
        node_indices = []
        feature_indices = []
        node_indptr = [0]
        feature_indptr = [0]

        for inputs in X:
            node_path = []
            feature_path = []
            node = self.tree
            node_path.append(node.id)
            feature_path.append(node.feature_index)
            while node.left:
                if inputs[node.feature_index] < node.threshold:
                    node = node.left
                else:
                    node = node.right
                node_path.append(node.id)
                feature_path.append(node.feature_index)
            node_indices.extend(node_path)

            # remove the feature index of the leaf node
            feature_path = feature_path[:-1]
            feature_indices.extend(feature_path)

            node_indptr.append(len(node_indices))
            feature_indptr.append(len(feature_indices))

        # Convert lists to numpy arrays
        node_indices = np.array(node_indices, dtype=np.int32)
        feature_indices = np.array(feature_indices, dtype=np.int32)
        node_indptr = np.array(node_indptr, dtype=np.int32)
        feature_indptr = np.array(feature_indptr, dtype=np.int32)

        return DecisionPath(node_indices, feature_indices, node_indptr, feature_indptr)

    def export_tree(self, feature_names, class_colors, class_names):
        import matplotlib.colors as mcolors

        # Define the colors for different conditions
        light_grey = "#DDDDDD"  # Grey color
        light_yellow = "#F7F7F7"  # Light grey color

        dot_data = ["digraph Tree {"]
        dot_data.append(
            'node [shape=box, style="filled, rounded", fontname="helvetica"] ;')
        dot_data.append('edge [fontname="helvetica"] ;')

        def add_node(node, node_id):
            if node.left or node.right:
                threshold = node.threshold
                # Handle the special case for fixed splits
                if threshold == 0.5:
                    #threshold_str = "== 0"
                    threshold_str = f"<= {self._custom_print(threshold)}"
                    fillcolor = light_grey
                else:
                    threshold_str = f"<= {self._custom_print(threshold)}"
                    fillcolor = light_yellow

                dot_data.append(
                    f'{node_id} [label="{feature_names[node.feature_index]} {threshold_str}\\n'
                    f'gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')

                left_id = node_id * 2 + 1
                right_id = node_id * 2 + 2
                add_node(node.left, left_id)
                add_node(node.right, right_id)
                dot_data.append(f'{node_id} -> {left_id} ;')
                dot_data.append(f'{node_id} -> {right_id} ;')
            else:
                # Leaf node: use the color of the predicted class
                fillcolor = class_colors[
                    node.predicted_class % len(class_colors)]
                dot_data.append(
                    f'{node_id} [label="gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')

        add_node(self.tree, 0)
        dot_data.append("}")
        return "\n".join(dot_data)

    def _custom_print(self, number):
        from decimal import Decimal, getcontext

        # Set a high precision to handle very small numbers
        getcontext().prec = 50

        # Convert the number to a decimal
        num = Decimal(number)

        # Convert to string
        num_str = format(num, 'f')

        # Split the string into the integer and decimal parts
        integer_part, decimal_part = num_str.split('.')

        # Find the first three non-zero consecutive decimal digits
        non_zero_count = 0
        for i, digit in enumerate(decimal_part):
            if digit != '0':
                non_zero_count += 1
                if non_zero_count == 3:
                    break

        # Join the integer part with the truncated decimal part
        formatted_num = integer_part + '.' + decimal_part[:i + 1]
        return formatted_num

    def export_decision_paths(self, decision_paths, feature_names, class_colors,
                              class_names, output_dir="decision_paths",
                              leaf_id=None):

        # Define the colors for different conditions
        light_grey = "#DDDDDD"  # Grey color
        light_yellow = "#F7F7F7"  # Light grey color

        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        node_path = decision_paths.node_indices[
                    decision_paths.node_indptr[0]: decision_paths.node_indptr[
                        1]]

        dot_data = ["digraph Tree {"]
        dot_data.append(
            'node [shape=box, style="filled, rounded", fontname="helvetica"] ;')
        dot_data.append('edge [fontname="helvetica"] ;')

        for i, node_id in enumerate(node_path):
            node = self._get_node_by_id(node_id)
            if node.left or node.right:
                threshold = node.threshold
                if i < len(node_path) - 1:
                    next_node_id = node_path[i + 1]
                    if next_node_id == node.left.id:
                        if threshold == 0.5:
                            threshold_str = "== 0"
                        else:
                            threshold_str = f"< {self._custom_print(threshold)}"
                    else:
                        if threshold == 0.5:
                            threshold_str = "== 1"
                        else:
                            threshold_str = f"> {self._custom_print(threshold)}"

                    if threshold == 0.5:
                        fillcolor = light_grey
                    else:
                        fillcolor = light_yellow
                else:
                    threshold_str = f"<= {self._custom_print(threshold)}"
                    fillcolor = light_yellow
                dot_data.append(
                    f'{node_id} [label="{feature_names[node.feature_index]} {threshold_str}\\n'
                    f'gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')
                if i < len(node_path) - 1:
                    dot_data.append(f'{node_id} -> {next_node_id} ;')
            else:
                # Leaf node: use the color of the predicted class
                fillcolor = class_colors[
                    node.predicted_class % len(class_colors)]
                dot_data.append(
                    f'{node_id} [label="gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')

        dot_data.append("}")

        file_name = os.path.join(output_dir,
                                 f"decision_path_leaf_{leaf_id}.dot")
        with open(file_name, "w") as f:
            f.write("\n".join(dot_data))

        graph = graphviz.Source("\n".join(dot_data))
        graph.render(filename=file_name, format='png', cleanup=True)

    def _get_node_by_id(self, node_id):
        # Helper function to get a node by its id
        stack = [self.tree]
        while stack:
            node = stack.pop()
            if node.id == node_id:
                return node
            if node.right is not None:
                stack.append(node.right)
            if node.left is not None:
                stack.append(node.left)
        return None

    def export_decision_paths_with_subtree(self, decision_paths, feature_names,
                                           class_colors, class_names,
                                           output_dir="decision_paths",
                                           leaf_id=None):

        # Define the colors for different conditions
        light_grey = "#DDDDDD"  # Grey color
        light_yellow = "#F7F7F7"  # Light grey color

        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        node_path = decision_paths.node_indices[
                    decision_paths.node_indptr[0]: decision_paths.node_indptr[
                        1]]

        dot_data = ["digraph Tree {"]
        dot_data.append(
            'node [shape=box, style="filled, rounded", fontname="helvetica"] ;')
        dot_data.append('edge [fontname="helvetica"] ;')

        def add_node(node, node_id):
            if node.left or node.right:
                threshold = node.threshold
                # Handle the special case for fixed splits
                if threshold == 0.5:
                    threshold_str = "== 0"
                    fillcolor = light_grey
                else:
                    threshold_str = f"<= {self._custom_print(threshold)}"
                    fillcolor = light_yellow

                dot_data.append(
                    f'{node_id} [label="{feature_names[node.feature_index]} {threshold_str}\\n'
                    f'gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')

                left_id = node_id * 2 + 1
                right_id = node_id * 2 + 2
                add_node(node.left, left_id)
                add_node(node.right, right_id)
                dot_data.append(f'{node_id} -> {left_id} ;')
                dot_data.append(f'{node_id} -> {right_id} ;')
            else:
                # Leaf node: use the color of the predicted class
                fillcolor = class_colors[
                    node.predicted_class % len(class_colors)]
                dot_data.append(
                    f'{node_id} [label="gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')

        for i, node_id in enumerate(node_path):
            node = self._get_node_by_id(node_id)
            if node.left or node.right:
                threshold = node.threshold
                if i < len(node_path) - 1:
                    next_node_id = node_path[i + 1]
                    if next_node_id == node.left.id:
                        if threshold == 0.5:
                            threshold_str = "== 0"
                        else:
                            threshold_str = f"< {self._custom_print(threshold)}"
                    else:
                        if threshold == 0.5:
                            threshold_str = "== 1"
                        else:
                            threshold_str = f"> {self._custom_print(threshold)}"

                    if threshold == 0.5:
                        fillcolor = light_grey
                    else:
                        fillcolor = light_yellow
                else:
                    threshold_str = f"<= {self._custom_print(threshold)}"
                    fillcolor = light_yellow
                dot_data.append(
                    f'{node_id} [label="{feature_names[node.feature_index]} {threshold_str}\\n'
                    f'gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')
                if i < len(node_path) - 1:
                    dot_data.append(f'{node_id} -> {next_node_id} ;')
            else:
                # Leaf node: use the color of the predicted class
                fillcolor = class_colors[
                    node.predicted_class % len(class_colors)]
                dot_data.append(
                    f'{node_id} [label="gini = {node.gini:.2f}\\nsamples = {node.num_samples}\\n'
                    f'value = {node.num_samples_per_class}\\nclass = {class_names[node.predicted_class]}", fillcolor="{fillcolor}"] ;')

        # Add the subtree for the final node in the decision path
        final_node = self._get_node_by_id(node_path[-1])
        if final_node.left or final_node.right:
            add_node(final_node, final_node.id)

        dot_data.append("}")

        file_name = os.path.join(output_dir,
                                 f"decision_path_leaf_{leaf_id}.dot")
        with open(file_name, "w") as f:
            f.write("\n".join(dot_data))

        graph = graphviz.Source("\n".join(dot_data))
        graph.render(filename=file_name, format='pdf', cleanup=True)


def build_combined_tree(original_tree, leaf_trees, X, y):
    """Construct a new tree where the leaves of the original tree are replaced with new trees."""
    original_tree_ = original_tree.tree

    # Calculate the total number of nodes needed (excluding leaves of the original tree)
    def count_non_leaf_nodes(node):
        if node.left is None and node.right is None:
            return 0
        left_count = count_non_leaf_nodes(node.left) if node.left else 0
        right_count = count_non_leaf_nodes(node.right) if node.right else 0
        return 1 + left_count + right_count

    non_leaf_nodes = count_non_leaf_nodes(original_tree_)
    total_nodes = original_tree.node_count
    for leaf in leaf_trees.values():
        total_nodes += leaf.node_count

    print(f"Total nodes in the combined tree: {total_nodes - len(leaf_trees)}")

    # Initialize the combined tree
    combined_tree = {}
    next_node_id = 0

    # Copy the structure of the original tree
    def copy_tree(node, combined_tree):
        nonlocal next_node_id
        new_node = CustomDecisionTree.Node(
            gini=node.gini,
            num_samples=node.num_samples,
            num_samples_per_class=node.num_samples_per_class,
            predicted_class=node.predicted_class,
            node_id=node.id,
            threshold=node.threshold,
            feature_index=node.feature_index
        )
        next_node_id += 1
        combined_tree[node.id] = new_node

        if node.left is not None:
            new_node.left = copy_tree(node.left, combined_tree)
        if node.right is not None:
            new_node.right = copy_tree(node.right, combined_tree)
        return new_node

    # Replace the leaf nodes with the new trees
    def replace_leaf_nodes(node, combined_tree):
        if node.left is None and node.right is None:
            if node.id in leaf_trees.keys():
                new_tree = leaf_trees[node.id]
                new_tree_root = new_tree.tree
                return copy_subtree(new_tree_root, combined_tree, node.id)
            else:
                return node
        if node.left is not None:
            node.left = replace_leaf_nodes(node.left, combined_tree)
        if node.right is not None:
            node.right = replace_leaf_nodes(node.right, combined_tree)
        return node

    # Copy subtree from the new tree to the combined tree
    def copy_subtree(node, combined_tree, node_id_if_leaf=None):
        nonlocal next_node_id
        if node_id_if_leaf is not None:
            id = node_id_if_leaf
        else:
            id = next_node_id
        new_node = CustomDecisionTree.Node(
            gini=node.gini,
            num_samples=node.num_samples,
            num_samples_per_class=node.num_samples_per_class,
            predicted_class=node.predicted_class,
            node_id=id,
            threshold=node.threshold,
            feature_index=node.feature_index,
        )
        combined_tree[id] = new_node

        if node.left is not None:
            new_node.left = copy_subtree(node.left, combined_tree)
            next_node_id += 1
        if node.right is not None:
            new_node.right = copy_subtree(node.right, combined_tree)
            next_node_id += 1
        return new_node

    combined_tree_root = copy_tree(original_tree_, combined_tree)
    combined_tree_root = replace_leaf_nodes(combined_tree_root, combined_tree)

    combined_tree_obj = CustomDecisionTree(n_classes=original_tree.n_classes,
                                           min_samples_leaf=original_tree.min_samples_leaf)
    combined_tree_obj.tree = combined_tree_root
    combined_tree_obj.node_count = len(combined_tree)

    # Print combined tree attributes for debugging
    print("\nCombined tree attributes:")
    print(f"Total nodes: {combined_tree_obj.node_count}")

    return combined_tree_obj


def traverse_nodes(node):
    """Utility function to traverse nodes in a tree and yield each node."""
    yield node
    if node.left is not None:
        yield from traverse_nodes(node.left)
    if node.right is not None:
        yield from traverse_nodes(node.right)

# Example usage
def example_usage():
    from sklearn.datasets import load_iris
    from sklearn.model_selection import train_test_split
    import graphviz

    # iris = load_iris()
    # X, y = iris.data, iris.target
    # n_classes = len(np.unique(y))

    # X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)
    #
    # clf = CustomDecisionTree(min_samples_leaf=20, n_classes=n_classes)
    # clf.fit(X_train, y_train)

    concept_names = ["thickness_small", "thickness_medium", "thickness_large",
                      "thickness_xlarge", "width_small", "width_medium", "width_large",
                      "width_xlarge", "length_small", "length_medium", "length_large",
                      "length_xlarge"]
    class_names = ["6", "8", "9"]
    n_classes = len(class_names)

    train_dl, val_dl, test_dl = get_mnist_dataLoader(batch_size=32)
    X_train = train_dl.dataset[:][1].numpy()
    y_train = train_dl.dataset[:][2].numpy()

    # Train the custom decision tree classifier on the training set
    clf = CustomDecisionTree(n_classes=n_classes, max_depth=1000, min_samples_leaf=300)
    clf.fit(X_train, y_train)

    def get_leaf_nodes(node):
        if node.left is None and node.right is None:
            return [node]
        leaves = []
        if node.left:
            leaves.extend(get_leaf_nodes(node.left))
        if node.right:
            leaves.extend(get_leaf_nodes(node.right))
        return leaves

    def get_samples_for_leaf(node, X, tree):
        """Return the indices of samples that end up in the given leaf node."""
        path = []

        def traverse(node, sample_indices):
            if node.left is None and node.right is None:
                if node.id == leaf.id:
                    path.extend(sample_indices)
                return
            if node.left:
                left_indices = [i for i in sample_indices if
                                X[i, node.feature_index] <= node.threshold]
                traverse(node.left, left_indices)
            if node.right:
                right_indices = [i for i in sample_indices if
                                 X[i, node.feature_index] > node.threshold]
                traverse(node.right, right_indices)

        traverse(tree, list(range(X.shape[0])))
        return path

    leaf_trees = {}
    leaf_nodes = get_leaf_nodes(clf.tree)
    for leaf in leaf_nodes:
        indices = get_samples_for_leaf(leaf, X_train, clf.tree)
        X_leaf, y_leaf = X_train[indices], y_train[indices]
        if len(np.unique(y_leaf)) > 1:
            leaf_tree = CustomDecisionTree(min_samples_leaf=1,
                                           n_classes=n_classes)
            leaf_tree.fit(X_leaf, y_leaf)
            leaf_trees[leaf.id] = leaf_tree

            # Export each individual leaf tree to Graphviz format
            leaf_dot_data = leaf_tree.export_tree(
                feature_names=concept_names,
                class_names=class_names,
                class_colors=get_light_colors(len(class_names))
            )
            leaf_graph = graphviz.Source(leaf_dot_data)
            leaf_graph.render(f"dt_with_dts_custom/leaf_tree_{leaf.id}", format='png',
                              cleanup=True)

    # Export the original tree to Graphviz format
    original_dot_data = clf.export_tree(
        feature_names=concept_names,
        class_names=class_names,
        class_colors=get_light_colors(len(class_names))
    )
    original_graph = graphviz.Source(original_dot_data)
    original_graph.render("dt_with_dts_custom/original_tree", format='png', cleanup=True)

    # Build combined tree
    combined_tree = build_combined_tree(clf, leaf_trees, X_train, y_train)

    # Export the combined tree to Graphviz format
    combined_dot_data = combined_tree.export_tree(
        feature_names=concept_names,
        class_names=class_names,
        class_colors=get_light_colors(len(class_names))
    )
    combined_graph = graphviz.Source(combined_dot_data)
    combined_graph.render("dt_with_dts_custom/combined_tree", format='png', cleanup=True)

#example_usage()