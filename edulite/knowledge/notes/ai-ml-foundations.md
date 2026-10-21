# AI and machine learning foundations

## What AI is, and how it differs from traditional programming
Artificial intelligence (AI) is the field of building systems that perform tasks we associate with intelligence: recognising images, understanding language, making decisions. In traditional programming a person writes explicit rules: input + rules → output. In machine learning, the computer is given examples of inputs with the desired outputs, and it learns the rules (a model) itself: inputs + outputs → rules. A spam filter written by hand checks for listed words; a machine-learning spam filter learns which patterns predict spam from thousands of labelled emails. Machine learning is one approach within AI, and deep learning is a kind of machine learning that uses large neural networks.

## Types of machine learning: supervised, unsupervised and reinforcement learning
- Supervised learning learns from labelled examples, where each input comes with the correct answer. Predicting a number is regression (house price); predicting a category is classification (spam or not spam).
- Unsupervised learning finds structure in unlabelled data, for example clustering customers into groups, or reducing many features to a few (dimensionality reduction).
- Reinforcement learning trains an agent by trial and error: it takes actions in an environment and receives rewards or penalties, learning a policy that maximises total reward over time (game-playing agents, robot control).
Self-supervised learning, used to pre-train language models, creates labels from the data itself, such as predicting the next word of a sentence.

## Datasets, features, labels, and training, validation and test sets
A dataset is a table of examples. Features are the input columns the model uses (size, number of rooms); the label (target) is what we want to predict (price). Split the data before training: the training set teaches the model; the validation set is used to compare models and tune hyperparameters (settings chosen by you, such as tree depth or learning rate); the test set is used only once at the end to estimate performance on new data. A common split is 70/15/15 or 80/10/10. Data leakage, where information from the test data influences training, makes results look better than they really are. Examples include scaling with statistics from the whole dataset, or the same person appearing in both training and test sets.

## Linear regression
Linear regression predicts a number with a straight-line relationship: ŷ = w·x + b for one feature, or a weighted sum of several features. Training finds the weights w and bias b that minimise the mean squared error (MSE), the average of (prediction − actual)² over the training examples. Squaring makes all errors positive and punishes large errors more. It is simple, fast and easy to interpret (each weight shows how much the prediction changes per unit of that feature), but it can't capture curved relationships unless you add transformed features.

## Classification and logistic regression
Classification predicts a category. Logistic regression, despite its name, is a classification method: it computes a weighted sum of the features and passes it through the sigmoid function σ(z) = 1 / (1 + e⁻ᶻ), giving a probability between 0 and 1, and then predicts the positive class if the probability is above a threshold (usually 0.5). It is trained by minimising binary cross-entropy (log loss), which heavily penalises confident wrong predictions. For more than two classes, the softmax function generalises the sigmoid.

## Evaluation metrics: accuracy, precision, recall, F1 and the confusion matrix
A confusion matrix counts true positives (TP), false positives (FP), true negatives (TN) and false negatives (FN).
- Accuracy = (TP + TN) / total. It is misleading on imbalanced data: if 99% of emails are not spam, a model that always says "not spam" scores 99%.
- Precision = TP / (TP + FP): of the items predicted positive, how many really are.
- Recall = TP / (TP + FN): of the real positives, how many were found.
- F1 score = 2 · precision · recall / (precision + recall), the harmonic mean, which balances the two.
For regression, use mean absolute error (MAE), mean squared error (MSE) or its square root (RMSE).

## Overfitting, underfitting and regularisation
Overfitting is when a model memorises the training data, including its noise, so training error is low but error on new data is high. Underfitting is when the model is too simple to capture the pattern, so error is high on both. Signs: a large gap between training and validation scores means overfitting; both scores poor means underfitting. Remedies for overfitting: more data, a simpler model, regularisation (L1 or L2 penalties on large weights), early stopping, dropout in neural networks, and cross-validation to choose settings. Remedies for underfitting: a more expressive model, better features, or training longer. This trade-off is often described as bias (too simple) versus variance (too sensitive to the training data).

## Decision trees
A decision tree makes predictions by asking a sequence of yes/no questions about the features ("Is age > 30?"), branching until it reaches a leaf with a prediction. Training chooses, at each node, the split that best separates the classes, measured by Gini impurity or entropy (information gain); for regression it uses variance reduction. Trees are easy to visualise and need no feature scaling, but deep trees overfit easily, so limit the depth or the minimum samples per leaf. Random forests (many trees trained on random subsets, then voting) and gradient boosting are usually much more accurate than a single tree.

## k-means clustering
k-means groups unlabelled data into k clusters: choose k, place k initial centroids, assign each point to its nearest centroid, move each centroid to the mean of its assigned points, and repeat until assignments stop changing. It is simple and fast but you must choose k (the "elbow method" helps); results depend on the starting centroids, so run it several times. It assumes roughly round, similar-sized clusters, and features should be scaled first, because distances are dominated by features with large numbers.

## k-nearest neighbours
k-nearest neighbours (k-NN) classifies a new point by looking at the k closest training examples and taking a majority vote (or the average for regression). It does no real training, since it just stores the data, but prediction is slow on large datasets because distances to every example must be computed. Scale the features first; small k is sensitive to noise and large k blurs the boundaries.

## Bias, fairness, privacy and responsible AI
Models learn from data, so they absorb its biases: a hiring model trained on past decisions can repeat past discrimination, and face recognition trained mostly on one group performs worse on others. Responsible AI practice includes checking performance separately for different groups, documenting data sources and limitations, keeping humans involved in high-stakes decisions, explaining predictions where possible, and protecting privacy by collecting only the data needed, anonymising it, and getting consent. A model's output is a prediction, not a fact: language models in particular can produce fluent but false statements (hallucinations), so important answers should be checked.
